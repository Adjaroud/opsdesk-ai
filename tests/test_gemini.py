import json

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import db
from app.agent import run_agent
from app.api import create_app
from app.llm import GeminiLLM, OpenAILLM, close_llm, create_llm, gemini_messages
from app.llm_config import LLMConfigError, llm_config
from app.tools import Tools, tool_schemas
from conftest import DRAFT, final


def completion(calls=None, content=None, reason=None):
    return {"id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "gemini-3.8-flash", "choices": [{"index": 0,
            "finish_reason": reason or ("tool_calls" if calls else "stop"),
            "message": {"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})}}]}


def function(call_id, name, args, signature=None):
    result = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if signature:
        result["extra_content"] = {"google": {"thought_signature": signature}}
    return result


def mock_gemini(monkeypatch, replies):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    seen = []
    iterator = iter(replies)
    real_client = openai.OpenAI
    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == "/v1beta/openai/chat/completions"
        assert request.headers["authorization"] == "Bearer fake-gemini-key"
        seen.append(json.loads(request.content))
        reply = next(iterator)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
    def client_factory(**kwargs):
        assert kwargs["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
        assert kwargs["max_retries"] == 0
        return real_client(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(openai, "OpenAI", client_factory)
    return seen


@pytest.mark.parametrize("provider,expected,model,key", [
    (None, OpenAILLM, "gpt-5-mini", "OPENAI_API_KEY"),
    ("openai", OpenAILLM, "gpt-5-mini", "OPENAI_API_KEY"),
    ("gemini", GeminiLLM, "gemini-3.8-flash", "GEMINI_API_KEY"),
])
def test_factory_defaults_without_network(monkeypatch, provider, expected, model, key):
    if provider:
        monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    monkeypatch.setenv(key, "fake-key")
    llm = create_llm()
    try:
        assert isinstance(llm, expected)
        assert llm.model == model
    finally:
        close_llm(llm)


@pytest.mark.parametrize("provider,key,other", [
    ("gemini", "GEMINI_API_KEY", "OPENAI_API_KEY"), ("openai", "OPENAI_API_KEY", "GEMINI_API_KEY")])
def test_selected_key_only(monkeypatch, provider, key, other):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    monkeypatch.setenv(other, "fake-other-key")
    assert llm_config().configured is False
    with pytest.raises(LLMConfigError, match=key):
        create_llm()


@pytest.mark.parametrize("provider,model", [("invalid-do-not-echo", ""), ("gemini", "gpt-5-mini"), ("openai", "gemini-3.8-flash")])
def test_invalid_configuration_is_explicit_and_safe(monkeypatch, provider, model):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    monkeypatch.setenv("OPSDESK_LLM_MODEL", model)
    with pytest.raises(LLMConfigError) as error:
        create_llm()
    assert "invalid-do-not-echo" not in str(error.value)


def test_gemini_single_call_and_arguments(monkeypatch):
    seen = mock_gemini(monkeypatch, [completion(calls=[function("call_1", "search_kb", {"query": "VPN connexion"}, "sig_1")])])
    llm = create_llm()
    try:
        decision = llm.decide("policy", [{"role": "user", "content": "VPN"}], tool_schemas())
        assert decision.calls[0].call_id == "call_1"
        assert decision.calls[0].name == "search_kb"
        assert decision.calls[0].arguments == json.dumps({"query": "VPN connexion"})
        assert decision.items[0]["message"]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig_1"
        assert len(seen[0]["tools"]) == 5
        assert "strict" not in seen[0]["tools"][0]["function"]
        assert "additionalProperties" not in json.dumps(seen[0]["tools"])
    finally:
        close_llm(llm)


def test_all_five_tools_two_tool_rounds_and_signatures(path, monkeypatch):
    first = [function("s", "search_kb", {"query": "VPN"}, "sig_A"),
             function("i", "get_service_incidents", {"service": "vpn"}), function("a", "get_employee_assets", {})]
    second = [function("t", "get_ticket_status", {"ticket_id": "TKT-001"}, "sig_B"), function("d", "draft_ticket", DRAFT)]
    seen = mock_gemini(monkeypatch, [completion(calls=first), completion(calls=second),
        completion(content=final(sources=["KB-001"], evidence=["INC-001", "AST-001", "TKT-001"]).text)])
    llm = create_llm()
    try:
        result = run_agent("VPN et matériel : consultez mon ticket puis préparez un brouillon", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert not result.error
    assert len(result.trace) == 5 and all(t["status"] == "ok" for t in result.trace)
    assert result.draft == DRAFT
    assert seen[1]["messages"][2]["tool_calls"] == first
    returned = seen[1]["messages"][3:6]
    assert [m["tool_call_id"] for m in returned] == ["s", "i", "a"]
    assert json.loads(returned[1]["content"])["untrusted_data"][0]["id"] == "INC-001"
    assert json.loads(returned[2]["content"])["untrusted_data"][0]["id"] == "AST-001"
    assistants = [m for m in seen[2]["messages"] if m.get("tool_calls")]
    assert assistants[0]["tool_calls"] == first
    assert assistants[1]["tool_calls"] == second
    assert [m["tool_call_id"] for m in seen[2]["messages"] if m["role"] == "tool"] == ["s", "i", "a", "t", "d"]
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5


@pytest.mark.parametrize("answer", ["not json", final(sources=["KB-999"]).text, final(evidence=["INC-999"]).text,
                                    final(evidence=["AST-999"]).text, final(evidence=["TKT-999"]).text])
def test_gemini_invalid_final_rejected(path, monkeypatch, answer):
    mock_gemini(monkeypatch, [completion(content=answer)])
    llm = create_llm()
    try:
        result = run_agent("Aide", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert result.error and not result.answer and not result.draft


def test_gemini_forbidden_tool_and_other_ticket_refused(path, monkeypatch):
    seen = mock_gemini(monkeypatch, [completion(calls=[function("c", "create_ticket", {}),
        function("t", "get_ticket_status", {"ticket_id": "TKT-002"})]), completion(content=final().text)])
    llm = create_llm()
    try:
        result = run_agent("Accéder au ticket d'un autre salarié", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert result.trace == [{"tool": "outil_non_autorise", "status": "erreur"}, {"tool": "get_ticket_status", "status": "refusé"}]
    assert "Demande fictive : wifi" not in json.dumps(seen)


def test_quota_no_fallback_even_with_both_keys(path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-must-not-be-used")
    seen = mock_gemini(monkeypatch, [httpx.Response(429, json={"error": {"message": "sensitive-provider-body", "code": "RESOURCE_EXHAUSTED"}})])
    with TestClient(create_app(path)) as client:
        token = client.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
        response = client.post("/chat", json={"message": "VPN"}, headers={"X-Session-Token": token})
    assert response.status_code == 200
    assert response.json()["error"] == "Quota Gemini atteint, réessayez plus tard. Aucun ticket créé."
    assert "sensitive-provider-body" not in response.text
    assert response.json()["draft"] is None
    assert len(seen) == 1
    with db.connect(path) as con:
        assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 5


@pytest.mark.parametrize("status", [400, 401, 403, 500])
def test_other_provider_errors_are_safe(path, monkeypatch, status):
    seen = mock_gemini(monkeypatch, [httpx.Response(status, json={"error": {"message": "secret-error-body"}})])
    llm = create_llm()
    try:
        result = run_agent("VPN", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert result.error and "secret-error-body" not in result.error and not result.draft
    assert len(seen) == 1


def test_final_only_structured_output_and_canonical_translation(monkeypatch):
    seen = mock_gemini(monkeypatch, [completion(content=final().text)])
    llm = create_llm()
    try:
        llm.decide("policy", [], tool_schemas(), allow_tools=False)
    finally:
        close_llm(llm)
    assert seen[0]["tool_choice"] == "none"
    assert seen[0]["response_format"]["type"] == "json_schema"
    canonical = [{"role": "user", "content": "hello"},
        {"type": "function_call", "call_id": "1", "name": "get_employee_assets", "arguments": "{}"},
        {"type": "function_call", "call_id": "2", "name": "search_kb", "arguments": '{"query":"VPN"}'},
        {"type": "function_call_output", "call_id": "1", "output": "[]"},
        {"type": "function_call_output", "call_id": "2", "output": "[]"}]
    translated = gemini_messages("policy", canonical)
    assert len(translated[2]["tool_calls"]) == 2
    assert [m["tool_call_id"] for m in translated[3:]] == ["1", "2"]


@pytest.mark.parametrize("provider,key,other", [("gemini", "GEMINI_API_KEY", "OPENAI_API_KEY"), ("openai", "OPENAI_API_KEY", "GEMINI_API_KEY")])
def test_health_and_chat_only_selected_key(path, monkeypatch, provider, key, other):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", provider)
    monkeypatch.setenv(other, "fake-other-key")
    with TestClient(create_app(path)) as client:
        health = client.get("/health").json()
        assert health["llm_provider"] == provider and not health["llm_configured"]
        token = client.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
        missing = client.post("/chat", json={"message": "VPN"}, headers={"X-Session-Token": token})
        assert missing.status_code == 503 and key in missing.json()["detail"]
        monkeypatch.setenv(key, "fake-selected-key")
        assert client.get("/health").json()["llm_configured"] is True


def test_invalid_provider_health_and_chat(path, monkeypatch):
    monkeypatch.setenv("OPSDESK_LLM_PROVIDER", "invalid-secret-value")
    with TestClient(create_app(path)) as client:
        health = client.get("/health").json()
        assert not health["llm_configured"] and "llm_config_error" in health
        assert "invalid-secret-value" not in json.dumps(health)
        token = client.post("/sessions", json={"employee_id": "EMP-001"}).json()["token"]
        response = client.post("/chat", json={"message": "VPN"}, headers={"X-Session-Token": token})
        assert response.status_code == 503


def test_gemini_timeout_has_no_retry_or_fallback(path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-unselected-key")
    seen = []
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    llm = GeminiLLM()
    llm.client.close()
    def timeout(request):
        seen.append(request.url.host)
        raise httpx.ReadTimeout("sensitive-timeout-data")
    llm.client = openai.OpenAI(api_key="fake-key", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                              max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(timeout)))
    try:
        result = run_agent("VPN", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert result.error and "sensitive-timeout-data" not in result.error
    assert seen == ["generativelanguage.googleapis.com"]
