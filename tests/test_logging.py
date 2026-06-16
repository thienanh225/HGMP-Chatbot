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
    assert calls["comment"] == "rất tốt"  # column is `comment` (header: timestamp,user_id,turn_id,rating,comment)


def test_webhook_failure_falls_back_to_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(escalation, "ESCALATION_CSV", tmp_path / "esc.csv")
    monkeypatch.setattr(escalation, "_post_webhook", lambda url, payload: False)
    dest = escalation.log_escalation("Tôi bị tiểu đường…", "guest", "qualified-person",
                                     secrets={"LOG_WEBHOOK_URL": "https://x/exec"})
    assert dest == "csv"
    assert (tmp_path / "esc.csv").exists()


def test_conversation_logs_turn_id(tmp_path, monkeypatch):
    """conversations schema carries turn_id so feedback can join back to a turn."""
    monkeypatch.setattr(escalation, "CONVERSATION_CSV", tmp_path / "conv.csv")
    escalation.log_conversation(
        "sess-1", "b2c", "stub/demo", None, ["hetik"], "Hetik có gì?", "trả lời mẫu",
        turn_id="turn-abc", secrets=None,
    )
    lines = (tmp_path / "conv.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",")[:2] == ["timestamp", "turn_id"]  # turn_id is column 2
    assert "turn-abc" in lines[1]


def test_feedback_turn_id_joins_conversation(tmp_path, monkeypatch):
    """A 👍/👎 feedback row references the same turn_id the conversation logged."""
    monkeypatch.setattr(escalation, "CONVERSATION_CSV", tmp_path / "conv.csv")
    monkeypatch.setattr(escalation, "FEEDBACK_CSV", tmp_path / "fb.csv")
    escalation.log_conversation(
        "sess-1", "b2c", "stub/demo", None, [], "Hetik có gì?", "trả lời",
        turn_id="turn-xyz", secrets=None,
    )
    escalation.log_feedback("", "sess-1", turn_id="turn-xyz", rating="like", secrets=None)
    conv = (tmp_path / "conv.csv").read_text(encoding="utf-8")
    fb = (tmp_path / "fb.csv").read_text(encoding="utf-8")
    assert "turn-xyz" in conv and "turn-xyz" in fb  # joinable
