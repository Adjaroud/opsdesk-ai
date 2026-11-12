import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.agent import run_agent
from app.api import create_app
from app.llm import Decision, FakeLLM
from app.tools import Tools
from conftest import DRAFT, call, final


@pytest.mark.parametrize("ticket_id", ["TKT-001", "TKT-999"])
def test_jade_ticket_refusal_is_safe_even_if_model_claims_status(path, ticket_id):
    fake = FakeLLM([Decision(calls=[call("get_ticket_status", ticket_id=ticket_id)]),
                    final(f"Le ticket {ticket_id} est en cours et appartient à Camille.", evidence=[ticket_id])])
    result = run_agent(f"Statut de {ticket_id} ?", Tools("EMP-005", path), fake)
    assert not result.error and not result.draft
    assert result.answer["evidence_ids"] == []
    assert "inaccessible ou inexistant" in result.answer["diagnosis"]
    assert "Camille" not in json.dumps(result.answer)
    assert "en cours" not in result.answer["diagnosis"]


def test_vpn_followup_draft_then_approval_uses_server_provenance(path):
    draft = {**DRAFT, "rationale": "Incident majeur actif INC-001 confirmé au précédent échange ; connexion VPN impossible."}
    fake = FakeLLM([
        Decision(calls=[call("get_service_incidents", service="vpn")]),
        final("Un incident VPN INC-001 est actif.", evidence=["INC-001"]),
        Decision(calls=[call("draft_ticket", **draft)]),
        final("Brouillon proposé concernant INC-001. Validation requise.", evidence=["INC-001"]),
    ])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        token = client.post("/sessions", json={"employee_id": "EMP-005"}).json()["token"]
        headers = {"X-Session-Token": token}
        assert not client.post("/chat", json={"message": "VPN impossible"}, headers=headers).json()["error"]
        result = client.post("/chat", json={"message": "OUI svp préparer un brouillon"}, headers=headers).json()
        assert not result["error"] and result["draft"]["priority"] == "P2"
        assert result["trace"] == [{"tool": "draft_ticket", "status": "ok"}]
        with db.connect(path) as con:
            assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5
        body = {"draft_id": result["draft_id"], "draft": result["draft"], "approved": True}
        first = client.post("/tickets", json=body, headers=headers).json()
        again = client.post("/tickets", json=body, headers=headers).json()
        assert first["id"] == again["id"] and again["replayed"]
        with db.connect(path) as con:
            assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 6


def test_only_server_provenance_not_assistant_text_can_authorize_reference(path):
    history = [{"role": "assistant", "content": final(evidence=["INC-001"]).text}]
    result = run_agent("Oui", Tools("EMP-001", path), FakeLLM([final(evidence=["INC-001"])]), history)
    assert result.error and result.diagnostic["code"] == "unverified_reference"


def test_restored_references_are_filtered_by_owner_and_current_incident_state(path):
    with db.connect(path) as con:
        con.execute("UPDATE incidents SET status='resolved' WHERE id='INC-001'")
    tools = Tools("EMP-005", path)
    tools.restore_references([{"sources": ["KB-007", "../secret", "KB-999"],
                               "evidence": ["TKT-001", "AST-001", "INC-001", "AST-005"]}])
    assert tools.evidence == {"AST-005"}
    assert set(tools.sources) == {"KB-007"}
    assert tools.sources["KB-007"]["origin"] == "session_revalidated"


def test_sessions_do_not_share_verified_references(path):
    fake = FakeLLM([Decision(calls=[call("get_service_incidents", service="vpn")]), final(evidence=["INC-001"]),
                    final(evidence=["INC-001"])])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        tokens = [client.post("/sessions", json={"employee_id": "EMP-005"}).json()["token"] for _ in range(2)]
        first = client.post("/chat", json={"message": "VPN"}, headers={"X-Session-Token": tokens[0]}).json()
        second = client.post("/chat", json={"message": "Oui"}, headers={"X-Session-Token": tokens[1]}).json()
    assert not first["error"]
    assert second["diagnostic"]["code"] == "unverified_reference"


def test_known_prose_reference_is_added_to_json_evidence(path):
    result = run_agent("VPN", Tools("EMP-005", path), FakeLLM([
        Decision(calls=[call("get_service_incidents", service="vpn")]), final("Incident INC-001 actif.")]))
    assert not result.error
    assert result.answer["evidence_ids"] == ["INC-001"]


def test_draft_reference_is_validated_too(path):
    draft = {**DRAFT, "rationale": "Incident fictif INC-999 mentionné sans preuve suffisante."}
    result = run_agent("Brouillon", Tools("EMP-005", path), FakeLLM([
        Decision(calls=[call("draft_ticket", **draft)]), final()]))
    assert result.error and not result.draft


def test_api_revalidates_incident_after_previous_exchange(path):
    fake = FakeLLM([Decision(calls=[call("get_service_incidents", service="vpn")]), final(evidence=["INC-001"]),
                    final(evidence=["INC-001"])])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        token = client.post("/sessions", json={"employee_id": "EMP-005"}).json()["token"]
        headers = {"X-Session-Token": token}
        client.post("/chat", json={"message": "VPN"}, headers=headers)
        with db.connect(path) as con:
            con.execute("UPDATE incidents SET status='resolved' WHERE id='INC-001'")
        result = client.post("/chat", json={"message": "Oui"}, headers=headers).json()
        assert result["diagnostic"]["code"] == "unverified_reference"


def test_source_can_be_cited_on_followup_after_revalidation(path):
    tools = Tools("EMP-005", path)
    tools.restore_references([{"sources": ["KB-007"], "evidence": []}])
    result = run_agent("Rappelez la procédure", tools, FakeLLM([final("Voir KB-007.")]))
    assert not result.error
    assert result.answer["source_ids"] == ["KB-007"]
    assert result.sources[0]["origin"] == "session_revalidated"


def test_revalidated_current_content_is_sent_to_model(path):
    with db.connect(path) as con:
        con.execute("UPDATE incidents SET summary='Nouvelle information officielle' WHERE id='INC-001'")
    tools = Tools("EMP-005", path)
    tools.restore_references([{"sources": ["KB-007"], "evidence": ["INC-001"]}])
    fake = FakeLLM([final(evidence=["INC-001"])])
    result = run_agent("Oui", tools, fake)
    assert not result.error
    assert "Nouvelle information officielle" in fake.requests[0]["messages"][-1]["content"]
    assert len(json.dumps(tools.revalidated_context(), ensure_ascii=False)) <= 6500
