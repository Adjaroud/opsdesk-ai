import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app import db
from app.api import create_app
from app.llm import Decision, FakeLLM, GeminiQuotaError
from conftest import DRAFT, call, final
from test_ui import UI, bind_backend


def count(path):
    with db.connect(path) as con:
        return con.execute("SELECT count(*) FROM tickets").fetchone()[0]


def click(page, label):
    return next(b for b in page.button if b.label == label).click().run(timeout=15)


def open_page(client, monkeypatch):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-ui-only")
    bind_backend(client, monkeypatch)
    return AppTest.from_file(UI).run(timeout=15)


def test_guide_uses_api_tools_and_only_click_creates_ticket(path, monkeypatch):
    fake = FakeLLM([
        Decision(calls=[call("get_service_incidents", service="vpn"), call("search_kb", query="VPN")]),
        final("Incident INC-001 actif, cause individuelle à confirmer.", sources=["KB-001"], evidence=["INC-001"]),
        Decision(calls=[call("draft_ticket", **DRAFT)]), final("Brouillon pour INC-001.", evidence=["INC-001"]),
    ])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        page = open_page(client, monkeypatch)
        assert len(fake.requests) == 0
        page.selectbox[0].select_index(4).run()
        click(page, "Envoyer la demande VPN")
        assert not page.exception and len(fake.requests) == 2
        trace = page.session_state["messages"][-1]["content"]["trace"]
        assert [t["tool"] for t in trace] == ["get_service_incidents", "search_kb"]
        assert count(path) == 5
        # Navigation and redraw must not submit another message or force tools.
        page.radio[0].set_value("Exploration libre").run()
        page.radio[0].set_value("Démo guidée").run()
        page.run()
        assert len(fake.requests) == 2
        click(page, "Demander un brouillon")
        assert not page.exception and len(fake.requests) == 4
        assert page.session_state["pending"]["draft"]["priority"] == "P2"
        assert count(path) == 5
        click(page, "Approuver et créer le ticket")
        assert not page.exception and count(path) == 6
        assert page.success[0].value == "Ticket réellement créé : TKT-006"
        with db.connect(path) as con:
            assert con.execute("SELECT employee_id FROM tickets WHERE id='TKT-006'").fetchone()[0] == "EMP-005"
        page.run()
        assert count(path) == 6 and len(fake.requests) == 4
        assert page.progress[0].value == 100


def test_guide_accepts_clarification_without_inventing_sources_or_draft(path, monkeypatch):
    fake = FakeLLM([final(question="Quel message d'erreur voyez-vous ?")])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        page = open_page(client, monkeypatch)
        click(page, "Envoyer la demande VPN")
        assert not page.exception
        assert page.session_state["pending"] is None and count(path) == 5
        assert any("L'agent demande une précision" in m.value for m in page.markdown)
        assert any("Aucune procédure citée" in c.value for c in page.caption)
        assert any("Aucun outil appelé" in c.value for c in page.caption)
        page.run()
        assert len(fake.requests) == 1


def test_guide_handles_missing_draft_without_advancing_to_approval(path, monkeypatch):
    fake = FakeLLM([final(), final("Je ne dispose pas encore d'informations suffisantes.")])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        page = open_page(client, monkeypatch)
        click(page, "Envoyer la demande VPN")
        click(page, "Demander un brouillon")
        assert not page.exception and count(path) == 5
        assert any("Aucun brouillon reçu" in m.value for m in page.markdown)
        assert not any(b.label == "Approuver et créer le ticket" for b in page.button)


def test_guide_quota_error_does_not_retry_on_rerun(path, monkeypatch):
    fake = FakeLLM([GeminiQuotaError("not-shown")])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        page = open_page(client, monkeypatch)
        click(page, "Envoyer la demande VPN")
        assert not page.exception and count(path) == 5
        assert "Quota Gemini atteint" in page.warning[0].value
        assert next(b for b in page.button if b.label == "Demander un brouillon").disabled
        page.run()
        assert len(fake.requests) == 1


def test_cancel_guided_draft_never_creates_ticket(client, path, monkeypatch):
    page = open_page(client, monkeypatch)
    # The prescribed fake chooses to draft immediately; the guide must accept it.
    click(page, "Envoyer la demande VPN")
    assert page.session_state["pending"]
    click(page, "Annuler")
    assert page.session_state["pending"] is None and count(path) == 5
    assert not page.exception


@pytest.mark.parametrize("action", ["employee", "restart"])
def test_guided_pending_draft_cannot_cross_new_session(client, path, monkeypatch, action):
    page = open_page(client, monkeypatch)
    click(page, "Envoyer la demande VPN")
    pending = dict(page.session_state["pending"])
    previous_token = page.session_state["token"]
    if action == "employee":
        page.selectbox[0].select_index(1).run()
    else:
        click(page, "Nouvelle conversation")
    assert not page.exception
    assert page.session_state["token"] != previous_token
    assert page.session_state["pending"] is None
    assert not page.session_state["messages"]
    response = client.post("/tickets", json={**pending, "approved": True}, headers={"X-Session-Token": page.session_state["token"]})
    assert response.status_code == 409 and count(path) == 5


def test_no_key_disables_all_guided_llm_actions(client, monkeypatch):
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    for label in ("Envoyer la demande VPN", "Demander un brouillon", "Envoyer"):
        assert next(b for b in page.button if b.label == label).disabled
    assert len(page.dataframe) == 2 and not page.exception


def test_guide_backend_failure_is_actionable_and_does_not_advance(client, path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    def transport(method, url, **kwargs):
        kwargs.pop("timeout", None)
        if url.endswith("/chat"):
            raise httpx.ReadTimeout("private-details")
        return client.request(method, url.replace("http://127.0.0.1:18000", ""), **kwargs)
    monkeypatch.setattr(httpx, "request", transport)
    page = AppTest.from_file(UI).run(timeout=15)
    click(page, "Envoyer la demande VPN")
    assert not page.exception and count(path) == 5
    assert "Backend indisponible" in page.error[0].value
    assert page.session_state["pending"] is None


def test_model_text_remains_plain_text_in_redesigned_ui(path, monkeypatch):
    text = '<script>alert("test")</script>'
    fake = FakeLLM([final(diagnosis=text)])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as client:
        page = open_page(client, monkeypatch)
        click(page, "Envoyer la demande VPN")
        assert any(t.value == text for t in page.text)
        assert not any(text in m.value for m in page.markdown)
        assert not page.exception
