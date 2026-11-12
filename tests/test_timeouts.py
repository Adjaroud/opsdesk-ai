import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.agent import run_agent
from app.api import create_app
from app.llm import create_llm, close_llm
from app.llm_config import LLMConfigError, llm_config
from app.tools import Tools


@pytest.mark.parametrize("provider,seconds", [("gemini", 60), ("openai", 25)])
def test_provider_timeout_defaults(monkeypatch, provider, seconds):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    assert llm_config().timeout_seconds == seconds
    assert llm_config().chat_timeout_seconds > 4 * seconds


@pytest.mark.parametrize("value", ["bad-secret", "NaN", "inf", "-1", "0", "121"])
def test_invalid_timeout_is_rejected_safely(monkeypatch, value):
    monkeypatch.setenv("OPSDESK_LLM_TIMEOUT_SECONDS", value)
    with pytest.raises(LLMConfigError) as error:
        llm_config()
    assert value not in str(error.value) or value in {"0", "-1"}


@pytest.mark.parametrize("provider,key", [("gemini", "GEMINI_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_configured_read_timeout_reaches_http_request_and_diagnostic(path, monkeypatch, provider, key):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    monkeypatch.setenv(key, "fake-key")
    monkeypatch.setenv("OPSDESK_LLM_TIMEOUT_SECONDS", "90")
    original_client = openai.OpenAI
    seen = []
    def handler(request):
        seen.append(request.extensions["timeout"])
        raise httpx.ReadTimeout("sensitive-data")
    def client_factory(**kwargs):
        return original_client(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(openai, "OpenAI", client_factory)
    llm = create_llm()
    try:
        result = run_agent("VPN", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert seen == [{"connect": 10, "read": 90, "write": 10, "pool": 5}]
    assert result.diagnostic["read_timeout_seconds"] == 90
    assert result.diagnostic["network_phase"] == "read"
    assert not result.draft and not result.trace
    assert "sensitive-data" not in result.error


def test_health_shares_full_chat_wait_budget_with_ui(path, monkeypatch):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("OPSDESK_LLM_TIMEOUT_SECONDS", "90")
    with TestClient(create_app(path)) as client:
        health = client.get("/health").json()
    assert health["llm_timeout_seconds"] == 90
    assert health["chat_timeout_seconds"] == 475


def test_ui_uses_backend_chat_timeout(client, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from test_ui import bind_backend
    monkeypatch.setenv("OPSDESK_LLM_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    bind_backend(client, monkeypatch)
    page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/ui.py")).run(timeout=15)
    assert not page.exception
    assert page.session_state["chat_timeout_seconds"] == 475
