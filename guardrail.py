"""
Medical safety gate (F4) — runs BEFORE generation on every non-raw message.

Hard constraint: a personal-medical question is NEVER sent to the answering
model. The classifier returns YES → the UI shows HANDOFF_MESSAGE, the question
is logged as a ticket, and the answering model is not called.

Tuning goal (this prototype): general wellness questions (meal plans, training,
sleep habits, general tips) must pass through as NO so the bot can answer them;
only PERSONAL / clinical questions escalate. The boundary lives in
prompts/guardrail_vi.md and is pinned by tests.

Model-agnostic: the classifier runs through the same LiteLLM gateway as the
answering model, on a cheap model from the selected provider (one key covers
both). Any error → escalate (fail-safe). Offline/stub model → deterministic
keyword heuristic so the no-key demo still escalates personal-medical questions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from gateway import GatewaySettings, complete

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
GUARDRAIL_PROMPT_PATH = ROOT / "prompts" / "guardrail_vi.md"

# Standard handoff message — wording fixed by HANDOFF.md §6. Owner approval to change.
HANDOFF_MESSAGE = (
    "Câu hỏi của anh/chị liên quan đến tình trạng sức khỏe cụ thể nên cần được "
    "chuyên gia y tế của công ty tư vấn trực tiếp. Em đã chuyển câu hỏi đến đội ngũ "
    "chuyên môn, anh/chị sẽ được liên hệ sớm nhất. Anh/chị vui lòng để lại "
    "số điện thoại hoặc email nhé."
)

# Personal-medical signals for the OFFLINE keyword fallback only (real classifier
# uses the LLM). Combines a personal marker with a clinical marker, or hits an
# always-escalate marker (pregnancy / child dosing / drug interaction).
_PERSONAL = re.compile(
    r"\b(tôi|em|mình|con (tôi|em|mình)|mẹ|bố|ba|chồng|vợ|người nhà|bé nhà)\b", re.IGNORECASE
)
_CLINICAL = re.compile(
    r"(tiểu đường|huyết áp|tim mạch|ung thư|xơ gan|viêm gan|suy thận|suy gan|"
    r"đột quỵ|tai biến|trầm cảm|bệnh nền|triệu chứng|chẩn đoán|đang điều trị|đang uống thuốc)",
    re.IGNORECASE,
)
_ALWAYS = re.compile(
    r"(mang thai|có bầu|cho con bú|tương tác thuốc|thuốc kê đơn|"
    r"tác dụng phụ|phản ứng phụ|"
    r"trẻ em|trẻ sơ sinh|cho bé|cho con|cho cháu|"
    r"con (tôi|em|mình)|bé nhà|cháu nhà|(con|bé|cháu).{0,10}tuổi)",
    re.IGNORECASE,
)


def load_guardrail_prompt() -> str:
    return GUARDRAIL_PROMPT_PATH.read_text(encoding="utf-8")


def parse_classifier_reply(reply: str) -> bool:
    """Interpret the classifier's raw reply. True = escalate. Pure/testable.

    Anything that is not a clear NO is treated as YES (fail-safe).
    """
    normalized = (reply or "").strip().upper()
    if normalized.startswith("NO"):
        return False
    if normalized.startswith("YES"):
        return True
    logger.warning("Guardrail classifier unclear reply %r — escalating", (reply or "")[:80])
    return True


def keyword_escalate(question: str) -> bool:
    """Deterministic offline heuristic (used only for stub/no-key mode)."""
    q = question or ""
    if _ALWAYS.search(q):
        return True
    return bool(_PERSONAL.search(q) and _CLINICAL.search(q))


def classify_question(question: str, settings: GatewaySettings,
                      context: list[str] | None = None) -> bool:
    """Return True if the question must be escalated. Fail-safe → True on error.

    `context` = recent prior user turns. It lets the gate catch follow-ups that
    rely on a condition disclosed earlier in the session (e.g. after "Tôi bị tiểu
    đường", a later "vậy uống được không?" still escalates).
    """
    if not settings.run_guardrail:
        return False

    ctx = [c for c in (context or []) if c and c.strip()]
    model = settings.classifier_model
    if model.startswith("stub/"):
        return keyword_escalate("\n".join([*ctx, question]))

    try:
        composed = question
        if ctx:
            prev = "\n".join(f"- {c}" for c in ctx)
            composed = f"Tin nhắn trước của người dùng:\n{prev}\nCâu hỏi hiện tại: {question}"
        prompt = load_guardrail_prompt().replace("{user_question}", composed)
        reply = complete(model=model, messages=[{"role": "user", "content": prompt}],
                         api_key=settings.api_key, max_tokens=4)
        return parse_classifier_reply(reply)
    except Exception:
        logger.exception("Guardrail classifier failed — escalating by default")
        return True
