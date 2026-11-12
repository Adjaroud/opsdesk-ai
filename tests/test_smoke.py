import pytest

import app.api
from app.llm import Decision, FakeLLM
from conftest import DRAFT, call, final
from scripts.smoke_llm import main


def test_smoke_requires_explicit_network_opt_in(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2


@pytest.mark.parametrize("provider,key", [("gemini", "GEMINI_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_smoke_without_key_makes_no_call(monkeypatch, provider, key):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    with pytest.raises(SystemExit, match=key):
        main(["--confirm-network"])


@pytest.mark.parametrize("confirmation,expected", [("APPROUVER", "second POST idempotent vérifié"), ("ANNULER", "Approbation annulée")])
def test_smoke_full_path_with_explicit_fake_llm(monkeypatch, tmp_path, capsys, confirmation, expected):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    fake = FakeLLM([
        Decision(calls=[call("get_service_incidents", service="vpn"), call("search_kb", query="VPN")]),
        final(sources=["KB-001"], evidence=["INC-001"]),
        Decision(calls=[call("get_employee_assets")]), final(evidence=["AST-001"]),
        Decision(calls=[call("get_ticket_status", ticket_id="TKT-001")]), final(evidence=["TKT-001"]),
        Decision(calls=[call("get_ticket_status", ticket_id="TKT-002")]), final(),
        Decision(calls=[call("draft_ticket", **DRAFT)]), final(),
    ])
    monkeypatch.setattr(app.api, "create_llm", lambda: fake)
    monkeypatch.setattr("builtins.input", lambda _: confirmation)
    main(["--confirm-network", "--approve-draft"])
    assert expected in capsys.readouterr().out


def test_single_decision_diagnostic_makes_one_call_and_executes_no_tools(monkeypatch, capsys):
    import scripts.smoke_llm as smoke
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    fake = FakeLLM([Decision(calls=[call("search_kb", query="VPN"), call("get_service_incidents", service="vpn")])])
    monkeypatch.setattr(smoke, "create_llm", lambda: fake)
    def forbidden(*args, **kwargs):
        raise AssertionError("Le mode diagnostic ne doit pas créer de base ni exécuter d'outils")
    monkeypatch.setattr(smoke, "seed", forbidden)
    main(["--confirm-network", "--first-decision-only"])
    assert len(fake.requests) == 1
    assert "Aucun outil exécuté" in capsys.readouterr().out


def test_single_decision_diagnostic_timeout_remains_private(monkeypatch, capsys):
    import scripts.smoke_llm as smoke
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(smoke, "create_llm", lambda: FakeLLM([TimeoutError("sensitive-data")]))
    with pytest.raises(SystemExit) as error:
        main(["--confirm-network", "--first-decision-only"])
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "timeout" in output and "sensitive-data" not in output
