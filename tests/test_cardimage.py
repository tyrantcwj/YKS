import pytest

from app import cardimage
from app.cardimage import resolve_fallback_image


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _client_returning(response):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None, headers=None):
            return response

    return _Client


@pytest.mark.asyncio
async def test_resolver_picks_best_match(monkeypatch):
    payload = {
        "data": [
            {
                "id": "mcd22-6",
                "name": "Lapras",
                "number": "6",
                "set": {"name": "McDonald's Collection 2022"},
                "images": {
                    "small": "https://images.pokemontcg.io/mcd22/6.png",
                    "large": "https://images.pokemontcg.io/mcd22/6_hires.png",
                },
            },
            {
                "id": "base3-25",
                "name": "Lapras",
                "number": "25",
                "set": {"name": "Fossil"},
                "images": {"large": "https://images.pokemontcg.io/base3/25_hires.png"},
            },
        ]
    }
    monkeypatch.setattr(cardimage.httpx, "AsyncClient", _client_returning(FakeResponse(200, payload)))

    url = await resolve_fallback_image("Lapras", "6", "McDonald's Collection 2022")
    assert url == "https://images.pokemontcg.io/mcd22/6_hires.png"


@pytest.mark.asyncio
async def test_resolver_returns_none_on_error_status(monkeypatch):
    monkeypatch.setattr(cardimage.httpx, "AsyncClient", _client_returning(FakeResponse(403, {})))
    assert await resolve_fallback_image("Lapras", "6", None) is None


@pytest.mark.asyncio
async def test_resolver_returns_none_when_no_name():
    assert await resolve_fallback_image("", None, None) is None
