import json

import pytest
import httpx
from fastapi.testclient import TestClient

from app.api import create_app
from app.llm import Decision, FakeLLM, ToolCall
from app.seed import seed


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    # Tests never load .env and cannot consume real provider credentials or quota.
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPSDESK_LLM_PROVIDER", "OPSDESK_LLM_MODEL", "OPSDESK_LLM_TIMEOUT_SECONDS", "OPSDESK_API_URL"):
        monkeypatch.delenv(name, raising=False)
    def reject_network(*args, **kwargs):
        raise AssertionError("Réseau réel interdit dans les tests : utiliser MockTransport.")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_network)


def final(diagnosis="Le diagnostic reste à confirmer.", sources=(), evidence=(), question="", advice=()):
    return Decision(text=json.dumps({"diagnosis": diagnosis, "advice": list(advice), "question": question,
                                     "source_ids": list(sources), "evidence_ids": list(evidence)}))


def call(name, **args):
    return ToolCall("call_" + name, name, json.dumps(args))


DRAFT = {"category": "vpn", "priority": "P2", "summary": "Connexion VPN impossible depuis ce matin",
         "rationale": "Incident majeur VPN confirmé ; activité distante affectée."}


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "test.db"
    seed(p)
    return p


@pytest.fixture
def client(path):
    fake = FakeLLM([Decision(calls=[call("draft_ticket", **DRAFT)]), final()])
    with TestClient(create_app(path, llm_factory=lambda: fake)) as c:
        yield c


@pytest.fixture
def headers(client):
    session = client.post("/sessions", json={"employee_id": "EMP-001"}).json()
    return {"X-Session-Token": session["token"]}
