"""Retrieval (KB grounding) + ROUTE-tag parsing tests."""
from escalation import clean_reply, parse_route
from retrieval import format_context, load_products, retrieve


def test_kb_loads_real_products():
    products = load_products()
    for stem in ["hetik", "femakul", "hemky", "hemky-d", "gueva", "niasom",
                 "binifa-ex", "binifa-baby"]:
        assert stem in products, stem
    assert len(products) == 8                   # nothing but the 8 real products


def test_retrieve_finds_relevant_product():
    chunks = retrieve("Hetik có thành phần gì cho gan?", k=3)
    ids = [c["id"] for c in chunks]
    assert "hetik" in ids
    assert format_context(chunks).startswith("[Nguồn:")


def test_retrieve_general_wellness_returns_nothing():
    # a wellness question with no product-domain terms drags in no product
    assert retrieve("Gợi ý thực đơn ăn uống lành mạnh trong ngày?", k=3) == []
    assert retrieve("Có mẹo nào giảm căng thẳng không?", k=3) == []


def test_retrieve_domain_wellness_maps_to_its_product_only():
    # sleep is Niasom's domain — a sleep question may surface Niasom, nothing else
    ids = [c["id"] for c in retrieve("Làm sao để ngủ ngon hơn?", k=3)]
    assert ids in ([], ["niasom"])


def test_parse_and_clean_route():
    assert parse_route("Trả lời...\nROUTE: customer-service") == "customer-service"
    assert parse_route("ROUTE: qualified-person") == "qualified-person"
    assert parse_route("không có thẻ") is None
    assert parse_route("ROUTE: nonsense") is None
    cleaned = clean_reply("Dạ em xin phép chuyển ạ.\n\nROUTE: customer-service")
    assert "ROUTE" not in cleaned
    assert cleaned == "Dạ em xin phép chuyển ạ."
