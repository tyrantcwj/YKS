from app import chs


def test_search_returns_simplified_cards():
    results = chs.search("喷火龙", limit=8)
    assert results, "expected bundled 国行 results for 喷火龙"
    assert all(r.card_id.startswith("chs:") for r in results)
    assert all(r.tcgdex_locale == "zh-cn" for r in results)
    # No duplicate card ids even though a card can sit in multiple collections.
    ids = [r.card_id for r in results]
    assert len(ids) == len(set(ids))
    # Exact-name matches rank ahead of longer names.
    assert results[0].name == "喷火龙"


def test_search_empty_query_returns_nothing():
    assert chs.search("") == []
    assert chs.search("   ") == []


def test_get_card_returns_payload_without_prices():
    first = chs.search("皮卡丘", limit=1)[0]
    payload = chs.get_card(first.card_id)
    assert payload is not None
    assert payload.card_id == first.card_id
    assert payload.name == "皮卡丘"
    assert payload.prices == []


def test_image_url_uses_forward_slashes_and_base(monkeypatch):
    monkeypatch.setattr(chs.settings_store, "get_str", lambda key: "https://mirror.test/repo/")
    card = chs._ChsCard(
        chs_id="1", name="测试", set_code="X", set_name="X", number="1/1", rarity="C",
        image_rel="img\\258\\13.png",
    )
    assert chs._image_url(card) == "https://mirror.test/repo/img/258/13.png"
