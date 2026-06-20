import pytest

from app import cards
from app.models import CardPayload, CardSearchResult
from app.tcgdex import CardNotFoundError


def _csr(card_id, locale="en"):
    return CardSearchResult(card_id=card_id, name=card_id, image_url=None, tcgdex_locale=locale)


@pytest.mark.asyncio
async def test_fetch_routes_chs_to_local_dataset():
    first = cards.chs.search("喷火龙", limit=1)[0]
    payload = await cards.fetch_card_payload(first.card_id)
    assert payload.card_id == first.card_id
    assert payload.prices == []


@pytest.mark.asyncio
async def test_fetch_pika_without_key_raises(monkeypatch):
    monkeypatch.setattr(cards.pikaqian, "_api_key", lambda: "")
    with pytest.raises(CardNotFoundError):
        await cards.fetch_card_payload("pika:abc")


@pytest.mark.asyncio
async def test_fetch_default_routes_to_tcgdex(monkeypatch):
    sentinel = CardPayload("swsh3-136", "Charizard", None, None, None, "{}", [])

    async def fake_tcgdex(card_id, locale=None):
        assert card_id == "swsh3-136"
        return sentinel

    monkeypatch.setattr(cards, "fetch_tcgdex_card", fake_tcgdex)
    assert await cards.fetch_card_payload("swsh3-136") is sentinel


@pytest.mark.asyncio
async def test_search_all_leads_with_simplified_for_chinese(monkeypatch):
    async def fake_tcgdex(query, limit=24):
        return [_csr("t1"), _csr("t2")]

    async def fake_pika(query, name_hint=None, limit=24):
        return [_csr("pika:1", "zh-cn")]

    monkeypatch.setattr(cards, "search_tcgdex", fake_tcgdex)
    monkeypatch.setattr(cards.pikaqian, "search", fake_pika)
    monkeypatch.setattr(cards.chs, "search", lambda q, limit=24, extra_terms=None: [_csr("chs:1", "zh-cn")])
    monkeypatch.setattr(cards.ja, "search", lambda q, limit=24, extra_terms=None: [_csr("jp:1", "ja")])

    results = await cards.search_all("喷火龙", limit=10)
    ids = [r.card_id for r in results]
    # Chinese query: chs first, then ja, then pika, then tcgdex; no duplicates.
    assert ids[0] == "chs:1"
    assert ids[1] == "jp:1"
    assert set(ids) == {"chs:1", "jp:1", "pika:1", "t1", "t2"}
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_search_all_leads_with_tcgdex_for_english(monkeypatch):
    async def fake_tcgdex(query, limit=24):
        return [_csr("t1"), _csr("t2")]

    async def fake_pika(query, name_hint=None, limit=24):
        return []

    monkeypatch.setattr(cards, "search_tcgdex", fake_tcgdex)
    monkeypatch.setattr(cards.pikaqian, "search", fake_pika)
    monkeypatch.setattr(cards.chs, "search", lambda q, limit=24, extra_terms=None: [_csr("chs:1", "zh-cn")])
    monkeypatch.setattr(cards.ja, "search", lambda q, limit=24, extra_terms=None: [_csr("jp:1", "ja")])

    results = await cards.search_all("charizard", limit=10)
    assert results[0].card_id == "t1"
