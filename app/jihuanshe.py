"""Experimental, best-effort 集换社 (Jihuanshe) price fetcher.

WARNING: 集换社 has no public API. The app / mini-program is encrypted (爱加密)
and uses anti-crawl cloud functions, so in practice this will usually return
nothing. It is disabled by default (``JHS_ENABLED``) and only runs when both a
``JHS_API_BASE`` endpoint and a per-subscription ``jhs_card_id`` are configured.
The dependable path for Chinese pricing is the manual CNY entry on the detail
page. This module always fails soft (returns ``[]``).
"""

import logging
from typing import Any

import httpx

from app import settings_store
from app.config import settings
from app.models import PricePoint

logger = logging.getLogger(__name__)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_price(payload: Any) -> float | None:
    """Pull a price out of a few plausible response shapes. Best-effort."""

    if isinstance(payload, dict):
        # Common nestings: {"data": {...}} / {"result": {...}}.
        for wrapper in ("data", "result", "card"):
            inner = payload.get(wrapper)
            if isinstance(inner, (dict, list)):
                price = _extract_price(inner)
                if price is not None:
                    return price
        for key in (
            "sell_price",
            "sale_price",
            "market_price",
            "lowest_price",
            "min_price",
            "price",
            "reference_price",
        ):
            price = _as_float(payload.get(key))
            if price is not None:
                return price
    elif isinstance(payload, list):
        for item in payload:
            price = _extract_price(item)
            if price is not None:
                return price
    return None


async def fetch_prices(jhs_card_id: str) -> list[PricePoint]:
    jhs_card_id = (jhs_card_id or "").strip()
    base = settings_store.get_str("jhs_api_base").strip().rstrip("/")
    if not settings_store.get_bool("jhs_enabled") or not jhs_card_id or not base:
        return []

    url = f"{base}/{jhs_card_id}"
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return []
        body = response.json()
    except Exception:  # noqa: BLE001 - experimental source must never raise
        logger.debug("集换社 fetch failed for %s", jhs_card_id, exc_info=True)
        return []

    price = _extract_price(body)
    if price is None:
        return []
    return [
        PricePoint(
            provider="jihuanshe",
            currency="CNY",
            variant="normal",
            market_price=price,
        )
    ]
