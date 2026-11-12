"""Native OpenAI Responses function calling; no network in deterministic tests."""
import os
import json
import httpx
from copy import deepcopy
from dataclasses import dataclass, field

from app.llm_config import LLMConfigError, llm_config, llm_timeout
from app.llm_errors import LLMFailure
from app.models import Answer


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class Decision:
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    items: list[dict] = field(default_factory=list)


class OpenAILLM:
    provider = "openai"
    def __init__(self):
        from openai import OpenAI
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY absente : le chat nécessite une clé. Les données restent consultables.")
        self.model = os.environ.get("OPSDESK_LLM_MODEL", "").strip() or "gpt-5-mini"
        self.timeout_seconds = llm_timeout(self.provider)
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                             timeout=httpx.Timeout(self.timeout_seconds, connect=10, write=10, pool=5), max_retries=0)

    def decide(self, instructions, messages, tools, allow_tools=True):
        response = self.client.responses.create(
            model=self.model, instructions=instructions, input=messages,
            tools=tools, tool_choice="auto" if allow_tools else "none",
            parallel_tool_calls=True, max_output_tokens=2200, store=False,
            text={"format": {"type": "json_schema", "name": "support_answer", "strict": True,
                             "schema": Answer.model_json_schema()}},
        )
        if response.status != "completed":
            if response.incomplete_details and response.incomplete_details.reason == "max_output_tokens":
                raise LLMFailure("output_limit")
            raise LLMFailure("response_rejected")
        calls = [ToolCall(item.call_id, item.name, item.arguments)
                 for item in response.output if item.type == "function_call"]
        return Decision(calls=calls, text=response.output_text,
                        items=[item.model_dump(exclude_none=True) for item in response.output])

    def close(self):
        self.client.close()


class GeminiQuotaError(RuntimeError):
    """Safe error marker; no provider response body or request is exposed."""


def gemini_schema(schema):
    """Remove unsupported constraints for transport; Pydantic remains strict locally.

    Our five tool schemas contain no $ref. Preserve properties, required, enum and
    types, including empty parameter objects, in the Google-compatible declaration.
    """
    unsupported = {"additionalProperties", "title", "minLength", "maxLength", "pattern", "maxItems", "minItems"}
    def convert(node):
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, value in node.items():
            if key in unsupported:
                continue
            # Property names are user schema names, not schema keywords.
            result[key] = {k: convert(v) for k, v in value.items()} if key == "properties" else convert(value)
        return result
    return convert(schema)


def gemini_messages(instructions, messages):
    """Translate canonical Responses items into correlated Chat Completions messages.

    Gemini adapter items use a private wrapper around the original assistant
    message. This retains Google extra_content/thought signatures without putting
    them in the UI, persisted history, or an OpenAI Responses request.
    """
    result = [{"role": "system", "content": instructions}]
    for item in messages:
        if item.get("type") == "gemini_assistant":
            result.append(deepcopy(item["message"]))
        elif item.get("type") == "function_call":
            call = {"id": item["call_id"], "type": "function",
                    "function": {"name": item["name"], "arguments": item["arguments"]}}
            if result[-1].get("tool_calls") and result[-1]["role"] == "assistant":
                result[-1]["tool_calls"].append(call)
            else:
                result.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif item.get("type") == "function_call_output":
            result.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
        elif item.get("role") in {"user", "assistant"}:
            result.append({"role": item["role"], "content": item["content"]})
        else:
            raise ValueError("Élément de conversation incompatible avec Gemini.")
    return result


class GeminiLLM:
    provider = "gemini"
    def __init__(self):
        from openai import OpenAI
        if not os.getenv("GEMINI_API_KEY", "").strip():
            raise LLMConfigError("GEMINI_API_KEY absente : le chat Gemini nécessite une clé.")
        self.model = os.getenv("OPSDESK_LLM_MODEL", "").strip() or "gemini-3.8-flash"
        self.timeout_seconds = llm_timeout(self.provider)
        self.client = OpenAI(
            api_key=os.environ["GEMINI_API_KEY"],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=httpx.Timeout(self.timeout_seconds, connect=10, write=10, pool=5), max_retries=0,
        )

    def decide(self, instructions, messages, tools, allow_tools=True):
        from openai import RateLimitError
        # Avoid combining response_format with tool mode for compatibility.
        # JSON is instructed on all turns, structured format only on the final-only
        # turn. run_agent validates every final answer with the original Answer.
        schema = Answer.model_json_schema()
        system = instructions + "\nLa réponse finale est uniquement un objet JSON, sans balises Markdown, conforme à ce schéma :\n" + json.dumps(schema, ensure_ascii=False)
        kwargs = {}
        if self.model.startswith(("gemini-3", "gemini-4")):
            kwargs["reasoning_effort"] = "low"
        if not allow_tools:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "support_answer", "schema": gemini_schema(schema)}}
        declarations = []
        for tool in tools:
            declaration = {"name": tool["name"], "description": tool["description"]}
            # Parameterless functions do not need an empty OBJECT declaration.
            # Their returned arguments are still validated by EmptyArgs locally.
            if tool["parameters"].get("properties"):
                declaration["parameters"] = gemini_schema(tool["parameters"])
            declarations.append({"type": "function", "function": declaration})
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=gemini_messages(system, messages),
                tools=declarations, tool_choice="auto" if allow_tools else "none",
                max_tokens=4096, **kwargs,
            )
        except RateLimitError:
            raise GeminiQuotaError("Quota Gemini atteint, réessayez plus tard. Aucun ticket créé.") from None
        if not response.choices:
            raise LLMFailure("response_rejected")
        if response.choices[0].finish_reason == "length":
            raise LLMFailure("output_limit")
        if response.choices[0].finish_reason not in {"stop", "tool_calls"}:
            raise LLMFailure("response_rejected")
        message = response.choices[0].message
        calls = [ToolCall(call.id, call.function.name, call.function.arguments) for call in message.tool_calls or []]
        # model_dump retains provider extensions on both the message and calls.
        preserved = message.model_dump(exclude_none=True)
        for key in ("refusal", "annotations", "audio"):
            preserved.pop(key, None)
        return Decision(calls=calls, text=message.content or "", items=[{
            "type": "gemini_assistant", "message": preserved}])

    def close(self):
        self.client.close()


def create_llm():
    config = llm_config()
    if not config.configured:
        raise LLMConfigError(f"{config.key_name} absente : configurez la clé du fournisseur sélectionné.")
    # Deliberately no fallback, retries, model discovery, or test call.
    return GeminiLLM() if config.provider == "gemini" else OpenAILLM()


def close_llm(llm):
    close = getattr(llm, "close", None)
    if callable(close):
        close()


class FakeLLM:
    """Explicit deterministic test double, never selected by the application UI."""
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.requests = []

    def decide(self, instructions, messages, tools, allow_tools=True):
        self.requests.append({"instructions": instructions, "messages": list(messages), "allow_tools": allow_tools})
        result = next(self.decisions)
        if isinstance(result, Exception):
            raise result
        return result
