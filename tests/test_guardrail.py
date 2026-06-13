"""
Guardrail + escalation-logging tests — run without API keys or heavy deps.

    cd chatbot && python -m pytest -q

The live LLM-classifier behaviour is exercised by the promptfoo suite once an
API key is available; here we pin the pure logic + the offline keyword heuristic.
"""
from escalation import log_escalation
from gateway import GatewaySettings
from guardrail import HANDOFF_MESSAGE, classify_question, keyword_escalate, parse_classifier_reply


# --- classifier reply parsing (fail-safe) ---------------------------------
def test_yes_escalates():
    assert parse_classifier_reply("YES") is True
    assert parse_classifier_reply("YES — bệnh lý nền") is True


def test_no_does_not_escalate():
    assert parse_classifier_reply("NO") is False
    assert parse_classifier_reply("no\n") is False
    assert parse_classifier_reply("NO.") is False


def test_unclear_reply_escalates():
    assert parse_classifier_reply("") is True
    assert parse_classifier_reply("Có thể") is True


def test_handoff_wording_fixed():
    assert "chuyên gia y tế" in HANDOFF_MESSAGE
    assert "số điện thoại hoặc email" in HANDOFF_MESSAGE


# --- offline keyword heuristic: wellness passes, personal-medical escalates -
def test_keyword_escalates_personal_medical():
    for q in [
        "Tôi bị tiểu đường, uống Gueva được không?",
        "Đang mang thai tháng thứ 5 thì dùng Femakul được không?",
        "Con tôi 4 tuổi dùng Binifa Baby liều bao nhiêu?",
        "Tôi đang uống thuốc huyết áp, dùng chung Hemky được không?",
    ]:
        assert keyword_escalate(q) is True, q


def test_keyword_allows_wellness_and_product():
    for q in [
        "Gợi ý cho em một thực đơn ăn uống lành mạnh.",
        "Cho em một kế hoạch tập luyện cho người mới bắt đầu.",
        "Làm sao để ngủ ngon hơn?",
        "Vitamin C có tác dụng gì?",
        "Hemky có những thành phần gì?",
    ]:
        assert keyword_escalate(q) is False, q


# --- escalation CSV ticket logging ----------------------------------------
def test_log_escalation_csv(tmp_path, monkeypatch):
    import escalation

    csv_path = tmp_path / "escalations.csv"
    monkeypatch.setattr(escalation, "ESCALATION_CSV", csv_path)

    dest = log_escalation("Tôi bị tiểu đường, uống được không?", "user_001", "qualified-person")
    assert dest == "csv"
    content = csv_path.read_text(encoding="utf-8")
    assert "tiểu đường" in content and "user_001" in content
    assert content.count("timestamp") == 1  # header once

    log_escalation("Câu hỏi thứ hai", "guest", "customer-service")
    assert csv_path.read_text(encoding="utf-8").count("timestamp") == 1


def test_classify_is_context_aware_offline():
    s = GatewaySettings(provider="Offline", model="stub/demo")
    # ambiguous follow-up alone → not escalated
    assert classify_question("Vậy uống Gueva được không?", s) is False
    # same follow-up, but a condition was disclosed a turn earlier → escalated
    assert classify_question("Vậy uống Gueva được không?", s,
                             context=["Tôi bị tiểu đường"]) is True
