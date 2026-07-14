"""
Orchestrator — the core request handler (shared logic with the production back end).

Flow per ChatRequest:
  raw     → call the bare model with just the user message (rig baseline).
  harness → medical gate → system prompt (no KB) → model → parse ROUTE.
  full    → medical gate → retrieve KB → system prompt + KB → model → parse ROUTE.

The medical gate (guardrail) runs BEFORE generation in harness/full; a YES means
the answering model is never called. The model itself is chosen at runtime via
GatewaySettings (LiteLLM string) — never hardcoded here.

A FastAPI back end would wrap this exact function; the Streamlit UI calls it
directly. Same contract, same logic — a config flag apart.
"""

from __future__ import annotations

import logging

from contract import ChatRequest, ChatResponse
from escalation import clean_reply, notify, parse_route
from gateway import GatewaySettings, complete_with_fallback
from guardrail import CONTACT_ACK, HANDOFF_MESSAGE, classify_question, is_contact_info
from prompts import build_system_prompt
from retrieval import format_context, retrieve

logger = logging.getLogger(__name__)

# In-memory session history (dev). Production: Redis/Postgres for multi-worker.
_sessions: dict[str, list[dict[str, str]]] = {}
MAX_HISTORY_TURNS = 8


def _history(session_id: str) -> list[dict[str, str]]:
    # Slicing always returns a fresh list, capped or not.
    return _sessions.get(session_id, [])[-MAX_HISTORY_TURNS * 2:]


def reset_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def handle_chat(req: ChatRequest, settings: GatewaySettings) -> ChatResponse:
    """Process one chat turn and return a ChatResponse."""

    # ---- raw: bare model, no guardrail / prompt / KB (rig baseline) ----------
    if req.config == "raw":
        reply, model_used = complete_with_fallback(
            settings.fallback_models, [{"role": "user", "content": req.message}],
            api_key=settings.api_key, max_tokens=settings.max_tokens,
        )
        return ChatResponse(answer=reply.strip(), route=None, sources=[],
                            model_used=model_used, config=req.config)

    # ---- 0. post-handoff contact capture -------------------------------------
    # The handoff asks for a phone/email; when the next message is exactly that,
    # attach it to the ticket (route stays qualified-person so the UI logs it)
    # and thank the user — don't re-classify and repeat the handoff.
    history = _history(req.session_id)
    if (history and history[-1]["role"] == "assistant"
            and history[-1]["content"] == HANDOFF_MESSAGE
            and is_contact_info(req.message)):
        notify("qualified-person", req.session_id, req.audience, req.message)
        _sessions[req.session_id] = (history + [
            {"role": "user", "content": req.message},
            {"role": "assistant", "content": CONTACT_ACK},
        ])[-MAX_HISTORY_TURNS * 2:]
        return ChatResponse(answer=CONTACT_ACK, route="qualified-person", sources=[],
                            model_used="none/contact-capture", config=req.config)

    # ---- 1. medical safety gate (before generation) -------------------------
    recent_user = [m["content"] for m in history if m["role"] == "user"][-2:]
    if classify_question(req.message, settings, context=recent_user):
        notify("qualified-person", req.session_id, req.audience, req.message)
        # Persist the turn so a disclosed condition is available to later turns.
        _sessions[req.session_id] = (history + [
            {"role": "user", "content": req.message},
            {"role": "assistant", "content": HANDOFF_MESSAGE},
        ])[-MAX_HISTORY_TURNS * 2:]
        return ChatResponse(answer=HANDOFF_MESSAGE, route="qualified-person", sources=[],
                            model_used=settings.classifier_model, config=req.config)

    # ---- 2. retrieve KB (full mode only) ------------------------------------
    chunks = retrieve(req.message, settings.retrieval_k) if req.config == "full" else []
    context = format_context(chunks)

    # ---- 3. assemble + call the model ---------------------------------------
    system_prompt = build_system_prompt(req.audience, context)
    messages = [{"role": "system", "content": system_prompt}, *history,
                {"role": "user", "content": req.message}]

    logger.info("chat | session=%s | config=%s | model=%s | audience=%s | chunks=%d",
                req.session_id, req.config, settings.answer_model, req.audience, len(chunks))

    raw_reply, model_used = complete_with_fallback(
        settings.fallback_models, messages,
        api_key=settings.api_key, max_tokens=settings.max_tokens,
    )

    # ---- 4. post-process: ROUTE tag, clean reply, dispatch ------------------
    route = parse_route(raw_reply)
    answer = clean_reply(raw_reply)
    if route:
        notify(route, req.session_id, req.audience, req.message)

    # ---- 5. update session history with clean content -----------------------
    _sessions[req.session_id] = (history + [
        {"role": "user", "content": req.message},
        {"role": "assistant", "content": answer},
    ])[-MAX_HISTORY_TURNS * 2:]

    return ChatResponse(answer=answer, route=route, sources=[c["id"] for c in chunks],
                        model_used=model_used, config=req.config)
