"""Fallback card-image resolver.

Many TCGdex entries (promos, McDonald's collections, some JP/CN cards) ship
with no `image` field at all, so the primary TCGdex image URL is missing.
When that happens we look the card up on pokemontcg.io (a different, broadly
complementary dataset) and reuse its artwork. Every lookup is best-effort and
fail-soft: any network/parse problem just yields ``None`` so sync never breaks.
"""

import logging
from typing import Any

import httpx

from app import settings_store
from app.config import settings

logger = logging.getLogger(__name__)

_POKEMONTCG_API = "https://api.pokemontcg.io/v2/cards"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _pick_best(
    cards: list[dict[str, Any]],
    name: str,
    number: str,
    set_name: str | None,
) -> dict[str, Any] | None:
    set_name_l = (set_name or "").strip().lower()
    name_l = name.strip().lower()

    def score(card: dict[str, Any]) -> int:
        value = 0
        card_set = card.get("set") if isinstance(card.get("set"), dict) else {}
        card_set_name = str(card_set.get("name") or "").lower()
        if set_name_l and card_set_name == set_name_l:
            value += 4
        elif set_name_l and (set_name_l in card_set_name or card_set_name in set_name_l):
            value += 2
        if number and str(card.get("number") or "").lstrip("0") == number.lstrip("0"):
            value += 2
        if str(card.get("name") or "").lower() == name_l:
            value += 1
        images = card.get("images") if isinstance(card.get("images"), dict) else {}
        if images.get("large") or images.get("small"):
            value += 1
        return value

    best = max(cards, key=score, default=None)
    return best


async def resolve_fallback_image(
    name: str | None,
    local_id: str | None,
    set_name: str | None,
) -> str | None:
    """Return a best-effort artwork URL from pokemontcg.io, or ``None``."""

    name = (name or "").strip()
    if not name:
        return None

    query_parts = [f'name:"{_escape(name)}"']
    number = (local_id or "").strip()
    if number:
        query_parts.append(f'number:"{_escape(number)}"')
    params = {"q": " ".join(query_parts), "pageSize": 25}

    headers: dict[str, str] = {}
    api_key = settings_store.get_str("pokemontcg_api_key").strip()
    if api_key:
        headers["X-Api-Key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(_POKEMONTCG_API, params=params, headers=headers)
        if response.status_code != 200:
            return None
        data = response.json().get("data")
    except Exception:  # noqa: BLE001 - fallback must never raise
        logger.debug("pokemontcg.io image fallback failed for %s", name, exc_info=True)
        return None

    if not isinstance(data, list) or not data:
        return None

    best = _pick_best(
        [card for card in data if isinstance(card, dict)],
        name,
        number,
        set_name,
    )
    if not best:
        return None
    images = best.get("images") if isinstance(best.get("images"), dict) else {}
    return images.get("large") or images.get("small")
