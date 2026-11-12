from concurrent.futures import ThreadPoolExecutor

from app import db
from app.api import create_app
from fastapi.testclient import TestClient
from conftest import DRAFT


def proposal(client, headers):
    result = client.post("/chat", json={"message": "Préparer un ticket VPN"}, headers=headers)
    assert result.status_code == 200
    result = result.json()
    assert not result["error"]
    return {"draft_id": result["draft_id"], "draft": result["draft"], "approved": True}


def count(path):
    with db.connect(path) as con:
        return con.execute("SELECT count(*) FROM tickets").fetchone()[0]


def test_health_seed_and_inventory(client, headers, path):
    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/employees").json()) == 6
    assert len(client.get("/me/assets", headers=headers).json()) == 2
    assert count(path) == 5
    assert client.get("/incidents/vpn", headers=headers).json()[0]["id"] == "INC-001"


def test_valid_ticket_and_other_employee_denied(client, headers):
    assert client.get("/tickets/TKT-001", headers=headers).json()["status"] == "en cours"
    assert client.get("/tickets/TKT-002", headers=headers).status_code == 404
    assert client.get("/tickets/TKT-999", headers=headers).status_code == 404


def test_session_required(client):
    assert client.get("/me/assets").status_code == 401
    assert client.post("/sessions", json={"employee_id": "EMP-999"}).status_code == 404


def test_draft_then_approval_and_idempotence(client, headers, path):
    body = proposal(client, headers)
    assert count(path) == 5
    first = client.post("/tickets", json=body, headers=headers)
    assert first.status_code == 201
    assert first.json()["id"] == "TKT-006"
    assert client.post("/tickets", json=body, headers=headers).json()["replayed"] is True
    assert count(path) == 6


def test_concurrent_approval(client, headers, path):
    body = proposal(client, headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/tickets", json=body, headers=headers), range(2)))
    assert all(r.status_code == 201 for r in responses)
    assert {r.json()["id"] for r in responses} == {"TKT-006"}
    assert count(path) == 6


def test_approval_requires_pending_draft(client, headers, path):
    body = {"draft_id": "a" * 32, "draft": DRAFT, "approved": True}
    assert client.post("/tickets", json=body, headers=headers).status_code == 409
    assert count(path) == 5


def test_cancelled_or_tampered_draft(client, headers, path):
    body = proposal(client, headers)
    altered = {**body, "draft": {**body["draft"], "summary": "Résumé modifié après proposition"}}
    assert client.post("/tickets", json=altered, headers=headers).status_code == 409
    assert client.delete("/drafts/" + body["draft_id"], headers=headers).status_code == 204
    assert client.post("/tickets", json=body, headers=headers).status_code == 409
    assert count(path) == 5


def test_approval_requires_true_and_rejects_forged_identity(client, headers):
    body = proposal(client, headers)
    assert client.post("/tickets", json={**body, "approved": False}, headers=headers).status_code == 422
    assert client.post("/tickets", json={**body, "employee_id": "EMP-002"}, headers=headers).status_code == 422


def test_other_session_cannot_approve(client, headers):
    body = proposal(client, headers)
    other = client.post("/sessions", json={"employee_id": "EMP-002"}).json()["token"]
    assert client.post("/tickets", json=body, headers={"X-Session-Token": other}).status_code == 409


def test_missing_key_and_input_bounds(path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(path)) as client:
        token = client.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
        headers = {"X-Session-Token": token}
        assert client.get("/health").json()["llm_configured"] is False
        assert client.post("/chat", json={"message": "VPN"}, headers=headers).status_code == 503
        for message in ["", " ", "x" * 2001]:
            assert client.post("/chat", json={"message": message}, headers=headers).status_code == 422
