import json

import pytest

from app.agent import POLICY, run_agent
from app.llm import Decision, FakeLLM
from app.tools import Tools
from conftest import DRAFT, call, final


@pytest.mark.parametrize("calls,answer", [
    ([call("search_kb", query="VPN connexion")], final(sources=["KB-001"])),
    ([call("get_service_incidents", service="vpn"), call("search_kb", query="VPN")], final(sources=["KB-001"], evidence=["INC-001"])),
    ([call("get_employee_assets")], final(evidence=["AST-001"])),
    ([call("get_ticket_status", ticket_id="TKT-001")], final(evidence=["TKT-001"])),
])
def test_scripted_scenarios(path, calls, answer):
    # These tests verify orchestration with prescribed decisions, not model intelligence.
    fake = FakeLLM([Decision(calls=calls), answer])
    result = run_agent("Demande fictive", Tools("EMP-001", path), fake)
    assert not result.error
    assert [t["tool"] for t in result.trace] == [c.name for c in calls]
    assert all(t["status"] == "ok" for t in result.trace)
    assert len(fake.requests) == 2


def test_ambiguous_request_can_clarify_without_action(path):
    result = run_agent("Ça ne fonctionne pas", Tools("EMP-001", path), FakeLLM([
        final(question="Quel service est concerné et quel message voyez-vous ?")]))
    assert result.answer["question"]
    assert not result.trace and not result.draft


def test_scripted_prohibited_software_refusal(path):
    result = run_agent("Installer un logiciel piraté", Tools("EMP-001", path), FakeLLM([
        Decision(calls=[call("search_kb", query="logiciel interdit")]),
        final("Installation interdite. Demandez une alternative approuvée au support.", sources=["KB-006"])]))
    assert not result.error and not result.draft
    assert "Refuse les logiciels interdits" in POLICY


def test_draft_and_final(path):
    result = run_agent("Propose un ticket", Tools("EMP-001", path), FakeLLM([
        Decision(calls=[call("draft_ticket", **DRAFT)]), final()]))
    assert not result.error and result.draft == DRAFT


@pytest.mark.parametrize("decision", [final(sources=["KB-999"]), final(evidence=["TKT-999"]),
                                     final("Consultez AST-999."), Decision(text="not JSON")])
def test_invalid_final_rejected(path, decision):
    result = run_agent("Aide", Tools("EMP-001", path), FakeLLM([decision]))
    assert result.error and not result.answer and not result.draft


def test_error_and_timeout_degrade_cleanly(path):
    tools = Tools("EMP-001", path)
    fake = FakeLLM([Decision(calls=[call("get_ticket_status", ticket_id="TKT-002")]),
                    final("Ticket inaccessible ou inexistant. Contactez le support officiel.")])
    result = run_agent("Le ticket d'un collègue", tools, fake)
    assert result.trace == [{"tool": "get_ticket_status", "status": "refusé"}]
    assert not result.error
    timeout = run_agent("VPN", tools, FakeLLM([TimeoutError("secret-never-shown")]))
    assert timeout.error and "secret-never-shown" not in timeout.error


def test_tool_exception_is_returned_to_model_without_details(path, monkeypatch):
    tools = Tools("EMP-001", path)
    def broken(*args):
        raise RuntimeError("secret-never-shown")
    monkeypatch.setattr(tools, "execute", broken)
    fake = FakeLLM([Decision(calls=[call("get_employee_assets")]), final("Inventaire indisponible.")])
    result = run_agent("Mon matériel", tools, fake)
    assert result.trace[0]["status"] == "erreur"
    assert "secret-never-shown" not in json.dumps(fake.requests)


def test_six_tool_limit_is_enforced(path):
    calls = [call("get_employee_assets") for _ in range(7)]
    result = run_agent("Aide", Tools("EMP-001", path), FakeLLM([Decision(calls=calls)]))
    assert result.error and len(result.trace) == 0


def test_four_decision_limit_and_final_without_tools(path):
    fake = FakeLLM([Decision(calls=[call("get_employee_assets")]) for _ in range(4)])
    result = run_agent("Aide", Tools("EMP-001", path), fake)
    assert result.error and len(fake.requests) == 4 and len(result.trace) == 3
    assert fake.requests[-1]["allow_tools"] is False


def test_six_calls_can_finish_in_four_decisions(path):
    fake = FakeLLM([Decision(calls=[call("get_employee_assets"), call("get_service_incidents", service="vpn")]) for _ in range(3)] + [final()])
    result = run_agent("Aide", Tools("EMP-001", path), fake)
    assert not result.error and len(result.trace) == 6


def test_history_is_bounded_and_preserves_clarification(path):
    fake = FakeLLM([final(question="Quel message apparaît ?")])
    history = [{"role": "user", "content": "VPN en panne"}] * 12
    run_agent("Erreur 42", Tools("EMP-001", path), fake, history)
    assert len(fake.requests[0]["messages"]) == 9
    assert fake.requests[0]["messages"][-1]["content"] == "Erreur 42"
