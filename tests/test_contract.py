"""Contract schema tests — the stable spine."""
import pytest
from pydantic import ValidationError

from contract import ChatRequest, ChatResponse


def test_request_defaults():
    req = ChatRequest(message="xin chào")
    assert req.audience == "b2c"
    assert req.config == "full"
    assert req.session_id  # auto-generated


def test_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_response_shape():
    resp = ChatResponse(answer="ok", model_used="stub/demo", config="full")
    assert resp.route is None
    assert resp.sources == []
    # round-trips through the contract keys the front end expects
    assert set(resp.model_dump()) == {"answer", "route", "sources", "model_used", "config"}
