from app import ja


def test_search_returns_official_japanese_cards():
    results = ja.search("リザードン", limit=2000)
    assert results, "expected bundled official JP results for リザードン"
    assert all(r.card_id.startswith("jp:") for r in results)
    assert all(r.tcgdex_locale == "ja" for r in results)
    # No duplicate ids, and far more than TCGdex's ~25 localized リザードン cards.
    ids = [r.card_id for r in results]
    assert len(ids) == len(set(ids))
    assert len(results) > 50


def test_search_via_extra_terms_for_english_query():
    # An English query maps to リザードン via the pokemon name table upstream;
    # here we confirm extra_terms is honored even when the raw query misses.
    results = ja.search("Charizard", limit=10, extra_terms=["リザードン"])
    assert results
    assert all(r.card_id.startswith("jp:") for r in results)


def test_search_empty_query_returns_nothing():
    assert ja.search("") == []
    assert ja.search("   ") == []


def test_get_card_returns_payload_without_prices():
    first = ja.search("リザードン", limit=1)[0]
    payload = ja.get_card(first.card_id)
    assert payload is not None
    assert payload.card_id == first.card_id
    assert payload.prices == []


def test_image_url_uses_base_override(monkeypatch):
    monkeypatch.setattr(ja.settings_store, "get_str", lambda key: "https://mirror.test/jp/")
    card = ja._JaCard(
        jp_id="1", name="テスト", set_name="X", number="1", card_type="ポケモン",
        image_rel="assets/images/card_images/large/X/1.jpg",
    )
    assert ja._image_url(card) == "https://mirror.test/jp/assets/images/card_images/large/X/1.jpg"
