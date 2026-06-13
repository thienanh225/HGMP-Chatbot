"""
promptfoo custom provider — runs the REAL chatbot pipeline for each test case.

This is the comparison rig: promptfoo varies the model (and audience/mode) while
calling the same orchestrator, guardrail, retrieval and prompts that ship in the
app. So what we compare is what we ship.

Each provider in promptfooconfig.yaml passes config: {provider, model, audience, mode}.
API keys are read from the environment (GEMINI_API_KEY, GROQ_API_KEY, ...).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # chatbot/ on path

import orchestrator
from contract import ChatRequest
from gateway import GatewaySettings


def call_api(prompt, options, context):
    cfg = (options or {}).get("config", {}) or {}
    settings = GatewaySettings(
        provider=cfg.get("provider", "Google Gemini"),
        model=cfg.get("model", "gemini-2.5-flash"),
        api_key="",  # litellm reads the provider key from the environment
        run_guardrail=cfg.get("mode", "full") != "raw",
        retrieval_k=4,
    )
    question = prompt if isinstance(prompt, str) else str(prompt)
    req = ChatRequest(
        message=question,
        session_id="promptfoo",
        audience=cfg.get("audience", "b2c"),
        config=cfg.get("mode", "full"),
    )
    resp = orchestrator.handle_chat(req, settings)
    return {
        "output": resp.answer,
        "metadata": {
            "route": resp.route or "",
            "sources": ",".join(resp.sources),
            "model_used": resp.model_used,
        },
    }
