"""
Retrieval layer — return the product-knowledge context for a question.

Two modes behind one interface (the production seam stays the same):

  • "simple" (default): a curated keyword map over the 8-product catalogue —
    no heavy dependencies, deterministic, and precise. A question only pulls in
    a product when it mentions that product's name, ingredients, or area; a
    general wellness question (meal plan, sleep, exercise) returns nothing, so
    the bot answers from general knowledge instead of pitching a product.
  • "vector" (scale): Chroma + BGE-M3 embeddings — add behind this same
    interface once the catalogue grows past ~20 products (plan: HANDOFF.md §7).

Either way `retrieve()` returns a list of {id, text} chunks and `format_context`
wraps them. `sources` in the ChatResponse = the ids here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTS_DIR = ROOT / "data" / "products"

# Curated trigger terms per product (lowercase). Distinctive words only — names,
# ingredients, and the product's area — so generic words don't cause false hits.
KEYWORDS: dict[str, list[str]] = {
    "hetik": ["hetik", "gan", "men gan", "gan nhiễm mỡ", "giải độc", "atiso", "atisô",
              "silymarin", "kế sữa", "bồ công anh", "milk thistle"],
    "femakul": ["femakul", "nội tiết", "kinh nguyệt", "mãn kinh", "tiền mãn kinh", "bốc hỏa",
                "estrogen", "phụ nữ", "black cohosh", "isoflavone"],
    "hemky": ["hemky", "xương khớp", "khớp", "sụn", "glucosamine", "msm", "curcumin",
              "viêm khớp", "thoái hóa khớp"],
    "hemky-d": ["hemky-d", "hemky d", "giảm đau", "thể thao", "vận động", "liễu trắng",
                "willow", "đau cơ"],
    "gueva": ["gueva", "giảm cân", "cân nặng", "mỡ máu", "cholesterol", "béo phì", "lipid",
              "garcinia", "hca", "chitosan"],
    "niasom": ["niasom", "mất ngủ", "giấc ngủ", "khó ngủ", "ngủ ngon", "đau đầu", "đau nửa đầu",
               "migraine", "jetlag", "lệch múi giờ", "melatonin"],
    "binifa-ex": ["binifa ex", "binifa", "men vi sinh", "lợi khuẩn", "tiêu hóa", "probiotic",
                  "đường ruột", "đầy hơi"],
    "binifa-baby": ["binifa baby", "men vi sinh trẻ", "lợi khuẩn cho bé", "tiêu hóa của bé"],
}


def load_products() -> dict[str, str]:
    """Load all real product docs as {stem: full_text}."""
    if not PRODUCTS_DIR.exists():
        return {}
    return {f.stem: f.read_text(encoding="utf-8").strip()
            for f in sorted(PRODUCTS_DIR.glob("*.md"))}


def retrieve(query: str, k: int = 4) -> list[dict]:
    """Return up to k product docs whose curated triggers appear in the query.

    Returns [] when nothing matches (e.g. a general wellness question) so the
    bot answers from general knowledge. Pure function (no network) — testable.
    """
    products = load_products()
    if not products:
        return []

    ql = query.lower()
    scored: list[tuple[int, str]] = []
    for stem, kws in KEYWORDS.items():
        if stem not in products:
            continue
        score = sum(1 for kw in kws if kw in ql)
        if stem in ql or stem.replace("-", " ") in ql:
            score += 3
        if score:
            scored.append((score, stem))

    scored.sort(reverse=True)
    return [{"id": stem, "text": products[stem]} for _, stem in scored[:k]]


def format_context(chunks: list[dict]) -> str:
    """Wrap retrieved chunks into the THÔNG TIN SẢN PHẨM block for the prompt."""
    if not chunks:
        return ""
    return "\n\n---\n\n".join(f"[Nguồn: {c['id']}]\n{c['text']}" for c in chunks)
