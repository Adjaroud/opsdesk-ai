"""Configuration only: never constructs a network client or loads local secrets."""
import os
import math
from dataclasses import dataclass


class LLMConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    key_name: str
    configured: bool
    timeout_seconds: float

    @property
    def chat_timeout_seconds(self):
        # Four decisions plus room for connect/write/pool phases and local tools.
        # SDK timeouts apply to network phases, not a strict wall-clock deadline.
        return 4 * (self.timeout_seconds + 25) + 15


def llm_timeout(provider):
    raw = os.getenv("OPSDESK_LLM_TIMEOUT_SECONDS", "").strip()
    try:
        value = float(raw) if raw else (60.0 if provider == "gemini" else 25.0)
    except ValueError:
        raise LLMConfigError("OPSDESK_LLM_TIMEOUT_SECONDS doit être un nombre entre 5 et 120.") from None
    if not math.isfinite(value) or not 5 <= value <= 120:
        raise LLMConfigError("OPSDESK_LLM_TIMEOUT_SECONDS doit être un nombre entre 5 et 120.")
    return value


def llm_config():
    provider = os.getenv("OPSDESK_LLM_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "gemini"}:
        raise LLMConfigError("OPSDESK_LLM_PROVIDER doit être openai ou gemini.")
    default_model, key_name = {
        "openai": ("gpt-5-mini", "OPENAI_API_KEY"),
        "gemini": ("gemini-3.8-flash", "GEMINI_API_KEY"),
    }[provider]
    model = os.getenv("OPSDESK_LLM_MODEL", "").strip() or default_model
    if (provider == "openai" and model.startswith("gemini-")) or (provider == "gemini" and model.startswith(("gpt-", "o1", "o3", "o4"))):
        raise LLMConfigError("OPSDESK_LLM_MODEL incompatible avec le fournisseur sélectionné ; effacez cette variable ou corrigez-la.")
    return LLMConfig(provider, model, key_name, bool(os.getenv(key_name, "").strip()), llm_timeout(provider))
