import json

import pytest

from app import tcgdex
from app.tcgdex import fetch_card, search_cards


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "id": "swsh3-136",
            "name": "Charizard",
            "image": "https://assets.tcgdex.net/en/swsh/swsh3/136",
            "set": {"name": "Darkness Ablaze"},
            "rarity": "Rare Holo VMAX",
            "pricing": {
                "tcgplayer": {
                    "holo": {
                        "marketPrice": 42.5,
                        "lowPrice": 39.0,
                        "midPrice": 43.0,
                        "highPrice": 60.0,
                    },
                    "reverse-holofoil": {
                        "marketPrice": 10.5,
                    }
                },
                "cardmarket": {
                    "trend": 20.5,
                    "low": 18.2,
                    "avg": 21.0,
                    "trend-holo": 41.2,
                    "low-holo": 38.1,
                    "avg-holo": 42.0,
                },
            },
        }

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.requested_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        self.requested_url = url
        return FakeResponse()


class FakeSearchResponse:
    def __init__(self, locale="en"):
        self.status_code = 200
        self.locale = locale

    def json(self):
        if self.locale == "ja":
            return [
                {
                    "id": "E1-016",
                    "localId": "016",
                    "name": "ピカチュウ",
                    "image": "https://assets.tcgdex.net/ja/e/e1/016",
                }
            ]
        return [
            {
                "id": "basep-1",
                "localId": "1",
                "name": "Pikachu",
                "image": "https://assets.tcgdex.net/en/base/basep/1",
            },
            {
                "id": "xyp-XY95",
                "localId": "XY95",
                "name": "Pikachu",
            },
        ]

    def raise_for_status(self):
        return None


class FakeSearchAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        locale = url.split("/v2/", 1)[1].split("/", 1)[0]
        return FakeSearchResponse(locale)


@pytest.mark.asyncio
async def test_fetch_card_extracts_provider_prices(monkeypatch):
    monkeypatch.setattr(tcgdex.httpx, "AsyncClient", FakeAsyncClient)
    payload = await fetch_card("swsh3-136")

    assert payload.name == "Charizard"
    assert payload.set_name == "Darkness Ablaze"
    assert payload.image_url == "https://assets.tcgdex.net/en/swsh/swsh3/136/high.webp"
    assert json.loads(payload.raw_json)["id"] == "swsh3-136"
    assert {price.provider for price in payload.prices} == {"tcgplayer", "cardmarket"}
    assert any(price.variant == "holo" and price.market_price == 42.5 for price in payload.prices)
    assert any(price.variant == "reverse" and price.market_price == 10.5 for price in payload.prices)


@pytest.mark.asyncio
async def test_search_cards_filters_by_name(monkeypatch):
    monkeypatch.setattr(tcgdex.httpx, "AsyncClient", FakeSearchAsyncClient)
    FakeSearchAsyncClient.calls = []

    results = await search_cards(" pikachu ", limit=1)

    assert FakeSearchAsyncClient.calls == [
        {
            "url": "https://api.tcgdex.net/v2/en/cards",
            "params": {"name": "like:pikachu"},
        }
    ]
    assert len(results) == 1
    assert results[0].card_id == "basep-1"
    assert results[0].tcgdex_locale == "en"
    assert results[0].image_url == "https://assets.tcgdex.net/en/base/basep/1/low.webp"


@pytest.mark.asyncio
async def test_search_cards_uses_japanese_locale_for_japanese_query(monkeypatch):
    monkeypatch.setattr(tcgdex.httpx, "AsyncClient", FakeSearchAsyncClient)
    FakeSearchAsyncClient.calls = []

    results = await search_cards("ピカチュウ", limit=1)

    assert FakeSearchAsyncClient.calls[0] == {
        "url": "https://api.tcgdex.net/v2/ja/cards",
        "params": {"name": "like:ピカチュウ"},
    }
    assert results[0].card_id == "E1-016"
    assert results[0].name == "ピカチュウ"
    assert results[0].tcgdex_locale == "ja"


@pytest.mark.asyncio
async def test_search_cards_dedupes_card_id_across_locales(monkeypatch):
    monkeypatch.setattr(tcgdex.httpx, "AsyncClient", FakeSearchAsyncClient)
    FakeSearchAsyncClient.calls = []

    # A CJK query fans out to several locales; the same card_id must not appear
    # twice and image-less results should sort after ones with artwork.
    results = await search_cards("皮卡丘", limit=10)

    card_ids = [result.card_id for result in results]
    assert len(card_ids) == len(set(card_ids))
    assert all(results[i].image_url or not results[i + 1].image_url for i in range(len(results) - 1))


class FakeFallbackResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.mark.asyncio
async def test_fetch_card_uses_fallback_image_when_missing(monkeypatch):
    card_without_image = {
        "id": "2022swsh-6",
        "localId": "6",
        "name": "Lapras",
        "set": {"name": "McDonald's Collection 2022"},
        "rarity": "None",
        "pricing": {},
    }

    class NoImageClient(FakeAsyncClient):
        async def get(self, url):
            self.requested_url = url
            return FakeFallbackResponse(200, card_without_image)

    monkeypatch.setattr(tcgdex.httpx, "AsyncClient", NoImageClient)

    async def fake_resolver(name, local_id, set_name):
        assert name == "Lapras"
        return "https://images.pokemontcg.io/mcd22/6_hires.png"

    monkeypatch.setattr(tcgdex, "resolve_fallback_image", fake_resolver)

    payload = await fetch_card("2022swsh-6")
    assert payload.image_url == "https://images.pokemontcg.io/mcd22/6_hires.png"
