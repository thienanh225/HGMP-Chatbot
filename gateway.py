"""
Model gateway — the ONLY place that talks to a model provider.

The model is a swappable component chosen at runtime (a LiteLLM `provider/model`
string). App logic never hardcodes a model name; it passes GatewaySettings here.
Swapping Claude / Gemini / Groq / OpenRouter / Mistral touches only config.

LiteLLM docs: https://docs.litellm.ai/docs/providers

Offline mode: any model string starting with "stub/" returns a deterministic
canned reply with no network call — used by tests and the no-key demo so the
full pipeline (contract → retrieval → routing) can run without API keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry — free-tier friendly. Model lists are sensible defaults;
# the UI also allows a custom model string since provider catalogs change.
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict] = {
    "Google Gemini": {
        "key_env": "GEMINI_API_KEY",
        "prefix": "gemini/",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "classifier": "gemini/gemini-2.5-flash-lite",
        "help": "https://aistudio.google.com/apikey",
    },
    "Groq": {
        "key_env": "GROQ_API_KEY",
        "prefix": "groq/",
        # qwen-2.5-32b deprecated Apr 2025 → qwen/qwen3-32b
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
        "classifier": "groq/llama-3.1-8b-instant",
        "help": "https://console.groq.com/keys",
    },
    "OpenRouter": {
        "key_env": "OPENROUTER_API_KEY",
        "prefix": "openrouter/",
        # OpenRouter reaches frontier models from many providers with one key.
        "models": [
            "anthropic/claude-sonnet-4.5",   # updated from claude-3.5-sonnet
            "openai/gpt-4o",
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "classifier": "openrouter/openai/gpt-4o-mini",
        "help": "https://openrouter.ai/keys",
    },
    "Cerebras": {
        "key_env": "CEREBRAS_API_KEY",
        "prefix": "cerebras/",
        # All Llama/Qwen models deprecated Feb–May 2026; only gpt-oss-120b on free public endpoints.
        # Use the "Nâng cao" field to try dedicated-endpoint models if you have access.
        "models": ["gpt-oss-120b"],
        "classifier": "cerebras/gpt-oss-120b",
        "help": "https://cloud.cerebras.ai/",
    },
}


def to_litellm_model(provider: str, model: str) -> str:
    """Compose the LiteLLM model string from a provider label + model id."""
    prefix = PROVIDERS.get(provider, {}).get("prefix", "")
    # If the caller already passed a fully-qualified string, don't double-prefix.
    if "/" in model and (model.startswith(prefix) or prefix == ""):
        return model
    return f"{prefix}{model}"


def classifier_model_for(provider: str, fallback: str) -> str:
    """Cheap model on the same provider for the guardrail (one key covers both)."""
    return PROVIDERS.get(provider, {}).get("classifier", fallback)


@dataclass
class GatewaySettings:
    """Everything the orchestrator needs to call models for one request."""

    provider: str = "Google Gemini"
    model: str = "gemini-2.5-flash"          # answering model (id within provider)
    api_key: str = ""                         # session-only; never persisted
    max_tokens: int = 1000
    run_guardrail: bool = True                # pre-generation medical safety gate
    retrieval_k: int = 4

    @property
    def answer_model(self) -> str:
        return to_litellm_model(self.provider, self.model)

    @property
    def classifier_model(self) -> str:
        return classifier_model_for(self.provider, self.answer_model)


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

def _stub_reply(messages: list[dict[str, str]]) -> str:
    """Deterministic offline reply (no network). For tests / no-key demo."""
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    return (
        "[CHẾ ĐỘ OFFLINE — không gọi mô hình thật]\n"
        "Đây là câu trả lời mẫu để kiểm tra luồng xử lý. "
        "Khi anh/chị nhập API key của một nhà cung cấp, hệ thống sẽ dùng mô hình thật.\n"
        f"(Đã nhận câu hỏi: {user[:160]})"
    )


def complete(model: str, messages: list[dict[str, str]], api_key: str = "", max_tokens: int = 1000) -> str:
    """Call the model via LiteLLM and return the reply text.

    `model` is a full LiteLLM string (e.g. 'gemini/gemini-2.5-flash',
    'openrouter/anthropic/claude-3.5-sonnet'). Raises on provider error so the
    caller can surface it.
    """
    if model.startswith("stub/"):
        return _stub_reply(messages)

    import litellm  # deferred import keeps pure modules/tests light

    # ponytail: LiteLLM honors the api_key kwarg for all configured providers —
    # no env-var mirroring needed. Verify with: python tools/batch_test.py --live
    kwargs: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if api_key:
        kwargs["api_key"] = api_key

    response = litellm.completion(**kwargs)
    return response.choices[0].message.content or ""
