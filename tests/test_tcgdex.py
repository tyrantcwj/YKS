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
    status_code = 200

    def json(self):
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
        return FakeSearchResponse()


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
            "params": {"name": "pikachu"},
        }
    ]
    assert len(results) == 1
    assert results[0].card_id == "basep-1"
    assert results[0].image_url == "https://assets.tcgdex.net/en/base/basep/1/low.webp"
