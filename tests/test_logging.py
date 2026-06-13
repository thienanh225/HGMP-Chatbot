"""Logging dispatch tests — webhook preferred, CSV fallback. No network."""
import escalation


def test_conversation_csv_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(escalation, "CONVERSATION_CSV", tmp_path / "conversations.csv")
    dest = escalation.log_conversation(
        "sess-1", "b2c", "stub/demo", None, ["hetik"], "Hetik có gì?", "trả lời mẫu", secrets=None,
    )
    assert dest == "csv"
    content = (tmp_path / "conversations.csv").read_text(encoding="utf-8")
    assert "hetik" in content and "sess-1" in content
    assert content.count("timestamp") == 1  # header once


def test_webhook_preferred_when_configured(monkeypatch):
    calls = {}
    monkeypatch.setattr(escalation, "_post_webhook",
                        lambda url, payload: calls.update(payload) or True)
    dest = escalation.log_feedback("rất tốt", "u1", secrets={"LOG_WEBHOOK_URL": "https://x/exec"})
    assert dest == "webhook"
    assert calls["sheet"] == "feedback"
    assert calls["feedback"] == "rất tốt"


def test_webhook_failure_falls_back_to_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(escalation, "ESCALATION_CSV", tmp_path / "esc.csv")
    monkeypatch.setattr(escalation, "_post_webhook", lambda url, payload: False)
    dest = escalation.log_escalation("Tôi bị tiểu đường…", "guest", "qualified-person",
                                     secrets={"LOG_WEBHOOK_URL": "https://x/exec"})
    assert dest == "csv"
    assert (tmp_path / "esc.csv").exists()
