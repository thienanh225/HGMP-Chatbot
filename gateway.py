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
import re
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
        # Free-tier RPD: gemini-2.5-flash=20, gemini-3.1-flash-lite=500, gemma-4=1500
        # gemini-2.5-pro removed (0 free quota)
        "models": [
            "gemini-2.5-flash",        # confirmed working, best quality
            "gemini-3.1-flash-lite",   # 500 RPD — best free daily limit
            "gemma-4-26b-a4b-it",      # 1500 RPD, 262K context
            "gemma-4-31b-it",          # 1500 RPD, largest Google free model
        ],
        "classifier": "gemini/gemini-3.1-flash-lite",  # 500 RPD >> 20 RPD of flash-lite
        "help": "https://aistudio.google.com/apikey",
    },
    "Groq": {
        "key_env": "GROQ_API_KEY",
        "prefix": "groq/",
        "models": ["llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
        "classifier": "groq/llama-3.1-8b-instant",
        "help": "https://console.groq.com/keys",
    },
    "OpenRouter": {
        "key_env": "OPENROUTER_API_KEY",
        "prefix": "openrouter/",
        # Free models only. Verify IDs at openrouter.ai/models?max_price=0
        # :free suffix required — without it OpenRouter charges credits.
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",   # 376M weekly tokens, reliable
            "openai/gpt-oss-120b:free",                  # 214B weekly tokens
            "google/gemma-4-26b-a4b-it:free",              # 4.38B weekly tokens
        ],
        "classifier": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        "help": "https://openrouter.ai/keys",
    },
    "Cerebras": {
        "key_env": "CEREBRAS_API_KEY",
        "prefix": "cerebras/",
        "models": ["gpt-oss-120b", "zai-glm-4.7"],  # zai-glm-4.7 is Preview
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

    @property
    def fallback_models(self) -> list[str]:
        """Selected model first, then remaining provider models as silent fallbacks."""
        provider_models = PROVIDERS.get(self.provider, {}).get("models", [])
        ordered = [self.model] + [m for m in provider_models if m != self.model]
        return [to_litellm_model(self.provider, m) for m in ordered]


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


def complete_with_fallback(
    models: list[str],
    messages: list[dict[str, str]],
    api_key: str = "",
    max_tokens: int = 1000,
) -> tuple[str, str]:
    """Try models in order; silently skip to next on 429 / quota exhaustion.

    Returns (reply, model_used_litellm_string).
    """
    last_err: Exception | None = None
    for model in models:
        try:
            return complete(model, messages, api_key=api_key, max_tokens=max_tokens), model
        except Exception as exc:
            s = str(exc).lower()
            if "429" in s or "rate" in s or "quota" in s or "limit" in s:
                logger.warning("rate-limited: %s — trying next model", model)
                last_err = exc
                continue
            raise
    raise last_err or RuntimeError("all models exhausted")


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
    content = response.choices[0].message.content or ""
    # ponytail: strip <think>…</think> blocks from reasoning models (Qwen3, etc.)
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
