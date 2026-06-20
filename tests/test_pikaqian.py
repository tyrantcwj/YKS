import pytest

from app import pikaqian


def test_parse_prices_reads_cents():
    card = {"prices": {"raw": 1599, "graded": {"PSA10": 9900, "PSA9": {"market": 4200}}}}
    points = pikaqian._parse_prices(card)
    by_provider = {p.provider: p.market_price for p in points}
    assert by_provider["pikaqian"] == 15.99
    assert by_provider["pikaqian-psa10"] == 99.0
    assert by_provider["pikaqian-psa9"] == 42.0


def test_parse_prices_handles_missing():
    assert pikaqian._parse_prices({}) == []
    assert pikaqian._parse_prices({"prices": None}) == []


def test_display_name_prefers_local():
    assert pikaqian._display_name({"name": "Charizard", "local_name": "喷火龙"}) == "喷火龙"
    assert pikaqian._display_name({"name": "Charizard"}) == "Charizard"


@pytest.mark.asyncio
async def test_search_disabled_without_key(monkeypatch):
    monkeypatch.setattr(pikaqian, "_api_key", lambda: "")
    assert await pikaqian.search("喷火龙", "Charizard") == []


@pytest.mark.asyncio
async def test_fetch_disabled_without_key(monkeypatch):
    monkeypatch.setattr(pikaqian, "_api_key", lambda: "")
    assert await pikaqian.fetch_card("pika:abc") is None
