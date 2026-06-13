"""
System-prompt builder.

`system_vi.md` holds the Vietnamese template (identity + guardrails + wellness
rules + ROUTE instructions) with two placeholders:
  {audience_note}  — filled per audience (b2c / b2b)
  {product_info}   — filled with retrieved KB context ("" in harness mode)

Any weakening of the guardrail language here is a major version bump (SemVer).
Keep this in sync with eval/promptfooconfig.yaml.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = ROOT / "prompts" / "system_vi.md"

_AUDIENCE_NOTE = {
    "b2c": (
        "ĐỐI TƯỢNG: khách hàng cá nhân trên trang sản phẩm. "
        "Giọng ấm áp, dễ hiểu, không dùng thuật ngữ chuyên môn khó."
    ),
    "b2b": (
        "ĐỐI TƯỢNG: nhân viên của công ty phân phối đối tác (B2B). "
        "Có thể dùng thuật ngữ chuyên môn về sản phẩm và công thức. "
        "Câu hỏi về công nợ, hạn mức, giá sỉ/giá hợp tác → thêm thẻ ROUTE: account-management. "
        "Câu hỏi về cơ hội phân phối, hợp tác bán hàng → thêm thẻ ROUTE: sales."
    ),
}


def build_system_prompt(audience: str, product_info: str = "") -> str:
    """Compose the full Vietnamese system prompt for the given audience."""
    template = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    note = _AUDIENCE_NOTE.get(audience, _AUDIENCE_NOTE["b2c"])
    if not product_info.strip():
        product_info = "(Chưa có thông tin sản phẩm liên quan cho câu hỏi này.)"
    return template.replace("{audience_note}", note).replace("{product_info}", product_info)
