"""
Guardrail + escalation-logging tests — run without API keys or heavy deps.

    cd chatbot && python -m pytest -q

The live LLM-classifier behaviour is exercised by the promptfoo suite once an
API key is available; here we pin the pure logic + the offline keyword heuristic.
"""
from escalation import log_escalation
from gateway import GatewaySettings
from guardrail import (
    HANDOFF_MESSAGE,
    classify_question,
    is_contact_info,
    is_greeting,
    keyword_escalate,
    parse_classifier_reply,
)


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


# --- greeting shortcut (real logs: "Hello"/"xin chào" escalated) -----------
def test_greetings_never_escalate():
    for q in ["Hello", "hello", "xin chào", "Xin chào ạ", "chào em", "Hi!",
              "cảm ơn em nhé", "test", "ok"]:
        assert is_greeting(q) is True, q
        s = GatewaySettings(provider="Offline", model="stub/demo")
        assert classify_question(q, s) is False, q


def test_medical_question_is_not_a_greeting():
    for q in ["Tôi bị tiểu đường, uống Gueva được không?",
              "chào em, tôi đang mang thai tháng thứ 5",  # greeting + medical → not pure greeting
              "Hetik có thành phần gì?"]:
        assert is_greeting(q) is False, q


# --- contact-info detection (post-handoff capture) --------------------------
def test_contact_info_detected():
    for m in ["903230286", "0903 230 286", "+84 903230286", "email tôi là an@example.com",
              "SĐT: 0912345678 nhé em"]:
        assert is_contact_info(m) is True, m


def test_normal_questions_are_not_contact_info():
    for m in ["Hetik có thành phần gì?", "Con tôi 4 tuổi dùng liều bao nhiêu?",
              "Giá bao nhiêu?"]:
        assert is_contact_info(m) is False, m


# --- classifier error → keyword fallback, not blanket escalation ------------
def test_classifier_error_falls_back_to_keywords(monkeypatch):
    import guardrail

    def boom(*a, **k):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(guardrail, "complete", boom)
    s = GatewaySettings(provider="Google Gemini", model="gemini-2.5-flash")
    # harmless product question: classifier down → keyword heuristic → answered
    assert classify_question("Hetik có thành phần gì?", s) is False
    # hard trigger: keyword heuristic still escalates fail-safe
    assert classify_question("Tôi bị tiểu đường, uống Gueva được không?", s) is True


def test_classify_is_context_aware_offline():
    s = GatewaySettings(provider="Offline", model="stub/demo")
    # ambiguous follow-up alone → not escalated
    assert classify_question("Vậy uống Gueva được không?", s) is False
    # same follow-up, but a condition was disclosed a turn earlier → escalated
    assert classify_question("Vậy uống Gueva được không?", s,
                             context=["Tôi bị tiểu đường"]) is True
