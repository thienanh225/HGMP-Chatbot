"""End-to-end orchestrator tests using the offline stub model (no API key).

Verifies the full pipeline plumbing — contract, guardrail gate, retrieval,
routing — deterministically, without any network call."""
import uuid

from contract import ChatRequest
from gateway import GatewaySettings
from guardrail import HANDOFF_MESSAGE

OFFLINE = GatewaySettings(provider="Offline", model="stub/demo", api_key="", run_guardrail=True)


def _ask(msg, config="full", audience="b2c"):
    # fresh session per call so single-turn tests stay independent
    req = ChatRequest(message=msg, session_id=str(uuid.uuid4()), audience=audience, config=config)
    return __import__("orchestrator").handle_chat(req, OFFLINE)


def test_personal_medical_is_gated_before_model():
    resp = _ask("Tôi bị tiểu đường, uống Gueva được không?")
    assert resp.answer == HANDOFF_MESSAGE
    assert resp.route == "qualified-person"
    assert resp.sources == []


def test_product_question_is_grounded():
    resp = _ask("Hetik có những thành phần gì?")
    assert resp.route is None
    assert "hetik" in resp.sources
    assert resp.model_used == "stub/demo"
    assert resp.config == "full"


def test_wellness_question_answered_without_escalation():
    resp = _ask("Gợi ý cho em một thực đơn ăn uống lành mạnh trong ngày.")
    assert resp.route is None
    assert resp.sources == []          # no product dragged in


def test_raw_mode_is_bare_model():
    resp = _ask("Xin chào", config="raw")
    assert resp.route is None
    assert resp.config == "raw"
    assert resp.model_used == "stub/demo"


def test_context_aware_followup_escalates():
    import orchestrator as orch
    sid = "mt-ctx"
    orch.reset_session(sid)
    orch.handle_chat(ChatRequest(message="Xin chào", session_id=sid, config="full"), OFFLINE)
    r1 = orch.handle_chat(ChatRequest(message="Tôi bị tiểu đường", session_id=sid, config="full"), OFFLINE)
    r2 = orch.handle_chat(ChatRequest(message="Vậy uống Gueva được không?", session_id=sid, config="full"), OFFLINE)
    assert r1.route == "qualified-person"   # discloses a condition → escalates
    assert r2.route == "qualified-person"   # follow-up inherits the context → escalates
