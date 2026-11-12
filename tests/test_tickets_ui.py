import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app import db
from app.api import create_app
from test_ui import UI


def bind_and_record(client, monkeypatch, failure=None):
    calls = []
    def transport(method, url, **kwargs):
        kwargs.pop("timeout", None)
        route = url.replace("http://127.0.0.1:18000", "")
        calls.append((method, route))
        if failure and failure.get("route") == route:
            return httpx.Response(failure.get("status", 500), json={"detail": "private-backend-detail"})
        return client.request(method, route, **kwargs)
    monkeypatch.setattr(httpx, "request", transport)
    return calls


def click(page, label):
    return next(b for b in page.button if b.label == label).click().run(timeout=15)


def ticket_select(page):
    return next(s for s in page.selectbox if s.label == "Ticket à consulter")


def ticket_table(page):
    # AppTest traverses the main area and sidebar independently of visual order.
    return next(frame.value for frame in page.dataframe if "priority" in frame.value.columns)


def listed_ids(page):
    return list(ticket_table(page)["id"])


def test_existing_tickets_and_details_need_no_llm_key(client, monkeypatch):
    calls = bind_and_record(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    page.radio[0].set_value("Mes tickets").run()
    assert not page.exception
    assert listed_ids(page) == ["TKT-001"]
    assert list(ticket_table(page).columns) == ["id", "category", "priority", "summary", "status"]
    assert ticket_select(page).value == "TKT-001"
    assert any(t.value == "Statut : en cours" for t in page.text)
    assert ("GET", "/tickets/TKT-001") in calls
    assert not any(route == "/chat" or route == "/tickets" for _, route in calls)
    assert not any(b.label == "Approuver et créer le ticket" for b in page.button)


def test_created_ticket_opened_highlighted_and_persists_after_new_conversation(client, path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-ui-test-key")
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    calls = bind_and_record(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    click(page, "Envoyer la demande VPN")  # FakeLLM prepares a draft, no ticket yet.
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5
    click(page, "Approuver et créer le ticket")
    assert page.success[0].value == "Ticket réellement créé : TKT-006"
    click(page, "Voir ce ticket dans Mes tickets")
    assert not page.exception and page.radio[0].value == "Mes tickets"
    assert listed_ids(page) == ["TKT-006", "TKT-001"]
    assert ticket_select(page).value == "TKT-006"
    assert any("DERNIER TICKET CRÉÉ" in caption.value for caption in page.caption)
    assert any(text.value == "Identifiant : TKT-006" for text in page.text)
    # Selection uses the detail endpoint instead of presenting a cached row.
    ticket_select(page).set_value("TKT-001").run()
    assert any(text.value == "Statut : en cours" for text in page.text)
    ticket_select(page).set_value("TKT-006").run()
    previous_token = page.session_state["token"]
    click(page, "Nouvelle conversation")
    assert page.session_state["token"] != previous_token
    assert not page.session_state["messages"]
    assert "TKT-006" in listed_ids(page)
    assert ticket_select(page).value == "TKT-006"
    page.run()
    assert "TKT-006" in listed_ids(page)
    # A fresh browser session has no UI highlight state, but SQLite still has it.
    fresh = AppTest.from_file(UI).run(timeout=15)
    fresh.radio[0].set_value("Mes tickets").run()
    assert not fresh.exception and listed_ids(fresh) == ["TKT-006", "TKT-001"]
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 6
    assert sum(route == "/chat" for _, route in calls) == 1
    assert sum(method == "POST" and route == "/tickets" for method, route in calls) == 1


def test_refresh_rereads_list_and_detail_once(client, path, monkeypatch):
    calls = bind_and_record(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    page.radio[0].set_value("Mes tickets").run()
    assert any(t.value == "Statut : en cours" for t in page.text)
    # Simulate a status changed outside the read-only UI, only in the test DB.
    with db.connect(path) as con:
        con.execute("UPDATE tickets SET status='résolu' WHERE id='TKT-001'")
    before = len(calls)
    click(page, "Actualiser la liste")
    assert calls[before:].count(("GET", "/me/tickets")) == 1
    assert calls[before:].count(("GET", "/tickets/TKT-001")) == 1
    assert ticket_table(page).iloc[0]["status"] == "résolu"
    assert any(t.value == "Statut : résolu" for t in page.text)
    assert not page.exception


def test_employee_change_does_not_keep_previous_list_or_detail(client, monkeypatch):
    bind_and_record(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    page.radio[0].set_value("Mes tickets").run()
    assert listed_ids(page) == ["TKT-001"]
    next(s for s in page.selectbox if s.label == "Salarié fictif").select_index(4).run()
    assert not page.exception and listed_ids(page) == ["TKT-005"]
    assert ticket_select(page).value == "TKT-005"
    assert not any(t.value == "Identifiant : TKT-001" for t in page.text)
    denied = client.get("/tickets/TKT-001", headers={"X-Session-Token": page.session_state["token"]})
    assert denied.status_code == 404


def test_empty_list_is_explicit_and_has_no_detail_selector(client, monkeypatch):
    calls = bind_and_record(client, monkeypatch)
    page = AppTest.from_file(UI).run(timeout=15)
    next(s for s in page.selectbox if s.label == "Salarié fictif").select_index(5).run()  # EMP-006 has no initial ticket.
    page.radio[0].set_value("Mes tickets").run()
    assert not page.exception
    assert any("Aucun ticket pour ce salarié" in notice.value for notice in page.info)
    assert not any(s.label == "Ticket à consulter" for s in page.selectbox)
    assert not any(route.startswith("/tickets/") for _, route in calls)


@pytest.mark.parametrize("route,status", [("/me/tickets", 500), ("/tickets/TKT-001", 500), ("/tickets/TKT-001", 404)])
def test_api_error_drops_stale_detail_and_refresh_recovers(client, monkeypatch, route, status):
    failure = {}
    bind_and_record(client, monkeypatch, failure=failure)
    page = AppTest.from_file(UI).run(timeout=15)
    page.radio[0].set_value("Mes tickets").run()
    assert any(t.value == "Statut : en cours" for t in page.text)
    failure.update(route=route, status=status)
    click(page, "Actualiser la liste")
    assert not page.exception
    assert page.error and page.warning
    assert not any(t.value.startswith("Statut :") for t in page.text)
    assert "private-backend-detail" not in " ".join(e.value for e in page.error)
    if route == "/me/tickets":
        assert not any(s.label == "Ticket à consulter" for s in page.selectbox)
    failure.clear()
    click(page, "Actualiser la liste")
    assert not page.exception
    assert any(t.value == "Statut : en cours" for t in page.text)


def test_created_ticket_survives_backend_restart(client, path):
    token = client.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
    headers = {"X-Session-Token": token}
    result = client.post("/chat", json={"message": "Préparez un brouillon"}, headers=headers).json()
    created = client.post("/tickets", json={"draft_id": result["draft_id"], "draft": result["draft"], "approved": True}, headers=headers).json()["id"]
    with TestClient(create_app(path)) as restarted:
        session = restarted.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
        new_headers = {"X-Session-Token": session}
        assert restarted.get("/me/tickets", headers=new_headers).json()[0]["id"] == created
        assert restarted.get("/tickets/" + created, headers=new_headers).json()["status"] == "ouvert"
