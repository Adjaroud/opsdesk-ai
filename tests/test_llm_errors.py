import json

import httpx
import pytest
from openai import APIStatusError

from app.agent import run_agent
from app.llm import Decision, FakeLLM, create_llm, close_llm
from app.llm_errors import LLMFailure
from app.tools import Tools, tool_schemas
from conftest import final
from test_gemini import completion, mock_gemini


@pytest.mark.parametrize("status,code", [(400, "invalid_request"), (401, "authentication"),
    (403, "permission"), (404, "model_not_found"), (422, "invalid_request"), (503, "provider_unavailable")])
def test_provider_errors_are_distinguished_without_sensitive_details(path, monkeypatch, status, code):
    mock_gemini(monkeypatch, [httpx.Response(status, json={"error": {"message": "fake-secret-body"}})])
    llm = create_llm()
    try:
        result = run_agent("VPN", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert result.diagnostic == {"code": code, "http_status": status, "phase": "model_request", "decision": 1}
    assert "fake-secret-body" not in json.dumps(result.__dict__)
    assert not result.trace and not result.draft


@pytest.mark.parametrize("reason,expected", [("length", "output_limit"), ("content_filter", "response_rejected")])
def test_completion_finish_reason_is_explained(path, monkeypatch, reason, expected):
    mock_gemini(monkeypatch, [completion(content="", reason=reason)])
    llm = create_llm()
    try:
        result = run_agent("VPN", Tools("EMP-001", path), llm)
    finally:
        close_llm(llm)
    assert result.diagnostic["code"] == expected
    assert result.diagnostic["phase"] == "model_request"
    assert not result.trace and not result.draft


def test_parameterless_tool_and_lower_reasoning_are_sent(monkeypatch):
    seen = mock_gemini(monkeypatch, [completion(content=final().text)])
    llm = create_llm()
    try:
        llm.decide("policy", [], tool_schemas())
    finally:
        close_llm(llm)
    inventory = next(t["function"] for t in seen[0]["tools"] if t["function"]["name"] == "get_employee_assets")
    assert "parameters" not in inventory
    assert seen[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize("decision,code", [(Decision(text="invalid-json"), "invalid_answer"),
    (final(sources=["KB-999"]), "unverified_reference")])
def test_invalid_answers_are_distinct_from_connection_failure(path, decision, code):
    result = run_agent("VPN", Tools("EMP-001", path), FakeLLM([decision]))
    assert result.diagnostic == {"code": code, "phase": "answer_validation", "decision": 1}
    assert not result.answer and not result.draft


def test_invalid_key_google_http400_reason(path):
    error = APIStatusError("fake-secret-message", response=httpx.Response(400, request=httpx.Request("POST", "https://example.invalid")),
        body={"details": [{"reason": "API_KEY_INVALID"}], "message": "fake-secret-message"})
    result = run_agent("VPN", Tools("EMP-001", path), FakeLLM([error]))
    assert result.diagnostic["code"] == "authentication"
    assert "fake-secret-message" not in json.dumps(result.__dict__)


def test_timeout_is_explicit_and_unknown_errors_stay_private(path):
    timeout = run_agent("VPN", Tools("EMP-001", path), FakeLLM([TimeoutError("fake-secret")]))
    assert timeout.diagnostic["code"] == "timeout"
    unknown = run_agent("VPN", Tools("EMP-001", path), FakeLLM([RuntimeError("fake-secret")]))
    assert unknown.diagnostic["code"] == "unexpected"
    assert "fake-secret" not in json.dumps(unknown.__dict__)
