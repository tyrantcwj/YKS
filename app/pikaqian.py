"""Optional online Simplified Chinese card source: the PikaQian API.

PikaQian (https://pikaqian.com/docs) is a REST API for 国行 (Simplified Chinese)
Pokémon TCG data: card metadata, public CDN images, and — on paid tiers — raw
and graded prices derived from real eBay sales. A ``pk_live_…`` API key is
required (set it on the /settings page); without one this module is inert.

Cards use a ``pika:<id>`` card_id so fetch/sync routes back here. Everything is
fail-soft: any missing key / network / shape error yields empty results so the
rest of search and sync keep working.
"""

import logging
from typing import Any

import httpx

from app import settings_store
from app.config import settings
from app.models import CardPayload, CardSearchResult, PricePoint

logger = logging.getLogger(__name__)

CARD_ID_PREFIX = "pika:"
_DEFAULT_API_BASE = "https://api.pikaqian.com/v1"


def _api_base() -> str:
    base = (settings_store.get_str("pikaqian_api_base") or _DEFAULT_API_BASE).strip()
    return (base or _DEFAULT_API_BASE).rstrip("/")


def _api_key() -> str:
    return settings_store.get_str("pikaqian_api_key").strip()


def enabled() -> bool:
    return bool(_api_key())


def _headers() -> dict[str, str]:
    return {"X-API-Key": _api_key(), "User-Agent": "YKS"}


def _display_name(card: dict[str, Any]) -> str:
    return str(card.get("local_name") or card.get("name") or card.get("id") or "")


def _set_name(card: dict[str, Any]) -> str | None:
    card_set = card.get("set")
    if isinstance(card_set, dict):
        return card_set.get("local_name") or card_set.get("name")
    return card.get("set_local_name") or card.get("set_name")


def _cents_to_usd(value: Any) -> float | None:
    try:
        return round(int(value) / 100, 2)
    except (TypeError, ValueError):
        return None


def _parse_prices(card: dict[str, Any]) -> list[PricePoint]:
    """Best-effort price extraction. Money is USD cents per the docs; graded
    tiers may be nested. Anything unparseable is simply skipped."""

    prices = card.get("prices")
    if not isinstance(prices, dict):
        return []
    points: list[PricePoint] = []
    raw = _cents_to_usd(prices.get("raw") or prices.get("raw_cents") or prices.get("market"))
    if raw is not None:
        points.append(PricePoint(provider="pikaqian", currency="USD", variant="normal", market_price=raw))
    graded = prices.get("graded")
    if isinstance(graded, dict):
        for label, value in graded.items():
            price = _cents_to_usd(value if not isinstance(value, dict) else value.get("market"))
            if price is not None:
                points.append(
                    PricePoint(
                        provider=f"pikaqian-{label.lower()}",
                        currency="USD",
                        variant="normal",
                        market_price=price,
                    )
                )
    return points


async def search(query: str, name_hint: str | None = None, limit: int = 24) -> list[CardSearchResult]:
    if not enabled():
        return []
    # PikaQian filters cards by their English ``name``; translate a Chinese query
    # via the Pokemon name map (passed in as name_hint) so 喷火龙 -> Charizard.
    term = (name_hint or query or "").strip()
    if not term:
        return []
    url = f"{_api_base()}/cards"
    params = {"name_contains": term, "page_size": min(limit, 50)}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(url, params=params, headers=_headers())
        if response.status_code >= 400:
            logger.debug("PikaQian search HTTP %s", response.status_code)
            return []
        body = response.json()
    except Exception:  # noqa: BLE001 - never let an optional source break search
        logger.debug("PikaQian search failed", exc_info=True)
        return []

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    results: list[CardSearchResult] = []
    for card in data:
        if not isinstance(card, dict) or not card.get("id"):
            continue
        results.append(
            CardSearchResult(
                card_id=f"{CARD_ID_PREFIX}{card['id']}",
                name=_display_name(card),
                image_url=card.get("image_url"),
                tcgdex_locale="zh-cn",
                local_id=str(card.get("number")) if card.get("number") is not None else None,
            )
        )
        if len(results) >= limit:
            break
    return results


async def fetch_card(card_id: str) -> CardPayload | None:
    if not enabled():
        return None
    raw_id = card_id[len(CARD_ID_PREFIX):] if card_id.startswith(CARD_ID_PREFIX) else card_id
    url = f"{_api_base()}/cards/{raw_id}"
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(url, headers=_headers())
        if response.status_code >= 400:
            return None
        card = response.json()
    except Exception:  # noqa: BLE001
        logger.warning("PikaQian card lookup failed for %s", card_id, exc_info=True)
        return None
    if not isinstance(card, dict) or not card.get("id"):
        return None

    import json as _json

    return CardPayload(
        card_id=card_id,
        name=_display_name(card),
        image_url=card.get("image_url"),
        set_name=_set_name(card),
        rarity=card.get("rarity"),
        raw_json=_json.dumps(card, ensure_ascii=True),
        prices=_parse_prices(card),
    )
