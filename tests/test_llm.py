import json

import httpx
from openai import OpenAI

from app.llm import OpenAILLM
from app.tools import tool_schemas


def test_real_sdk_adapter_offline_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPSDESK_LLM_MODEL", "configured-model")
    seen = []
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0, "status": "completed",
            "model": "configured-model", "output": [
                {"type": "function_call", "id": "fc_test", "call_id": "call_test", "name": "get_employee_assets", "arguments": "{}", "status": "completed"}],
        })
    adapter = OpenAILLM()
    adapter.client.close()
    adapter.client = OpenAI(api_key="fake-test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        decision = adapter.decide("policy", [{"role": "user", "content": "Mon matériel"}], tool_schemas())
        assert decision.calls[0].name == "get_employee_assets"
        assert decision.items[0]["call_id"] == "call_test"
        assert seen[0]["model"] == "configured-model"
        assert seen[0]["store"] is False
        assert seen[0]["text"]["format"]["strict"] is True
        adapter.decide("policy", [], tool_schemas(), allow_tools=False)
        assert seen[1]["tool_choice"] == "none"
    finally:
        adapter.client.close()
