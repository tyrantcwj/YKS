import json
import re
from typing import Any

import httpx

from app.config import settings
from app.models import CardPayload, CardSearchResult, PricePoint


class CardNotFoundError(ValueError):
    pass


SUPPORTED_SEARCH_LOCALES = ("en", "ja", "zh-tw", "zh-cn")
LOCALE_LABELS = {
    "en": "英文",
    "ja": "日文",
    "zh-tw": "繁中",
    "zh-cn": "简中",
}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_variant(variant: str) -> str:
    return {
        "holofoil": "holo",
        "reverse-holofoil": "reverse",
        "reverseHolofoil": "reverse",
    }.get(variant, variant)


def _image_url(card: dict[str, Any]) -> str | None:
    image = card.get("image")
    if not image:
        return None
    if str(image).startswith("http"):
        return f"{image}/high.webp"
    return None


def _brief_image_url(card: dict[str, Any]) -> str | None:
    image = card.get("image")
    if not image:
        return None
    if str(image).startswith("http"):
        return f"{image}/low.webp"
    return None


def _set_name(card: dict[str, Any]) -> str | None:
    card_set = card.get("set")
    if isinstance(card_set, dict):
        return card_set.get("name")
    return None


def _tcgplayer_prices(pricing: dict[str, Any]) -> list[PricePoint]:
    provider = pricing.get("tcgplayer")
    if not isinstance(provider, dict):
        return []

    prices: list[PricePoint] = []
    for variant, values in provider.items():
        if not isinstance(values, dict):
            continue
        point = PricePoint(
            provider="tcgplayer",
            currency="USD",
            variant=_normalize_variant(variant),
            market_price=_as_float(values.get("marketPrice")),
            low_price=_as_float(values.get("lowPrice")),
            mid_price=_as_float(values.get("midPrice")),
            high_price=_as_float(values.get("highPrice")),
            direct_price=_as_float(values.get("directLowPrice")),
        )
        if point.display_price is not None:
            prices.append(point)
    return prices


def _cardmarket_prices(pricing: dict[str, Any]) -> list[PricePoint]:
    provider = pricing.get("cardmarket")
    if not isinstance(provider, dict):
        return []

    variants = [
        ("standard", "trend", "low", "avg", "avg1", "avg7", "avg30"),
        ("holo", "trend-holo", "low-holo", "avg-holo", "avg1-holo", "avg7-holo", "avg30-holo"),
    ]
    prices: list[PricePoint] = []
    for variant, trend_key, low_key, avg_key, avg1_key, avg7_key, avg30_key in variants:
        point = PricePoint(
            provider="cardmarket",
            currency="EUR",
            variant=variant,
            trend_price=_as_float(provider.get(trend_key)),
            low_price=_as_float(provider.get(low_key)),
            market_price=_as_float(provider.get(avg_key)),
            avg1_price=_as_float(provider.get(avg1_key)),
            avg7_price=_as_float(provider.get(avg7_key)),
            avg30_price=_as_float(provider.get(avg30_key)),
        )
        if point.display_price is not None:
            prices.append(point)
    return prices


def _safe_locale(locale: str | None) -> str:
    locale = (locale or settings.tcgdex_locale).strip().lower()
    return locale if locale else settings.tcgdex_locale


def _api_base() -> str:
    base = (settings.tcgdex_api_base or "https://api.tcgdex.net/v2").strip().rstrip("/")
    return base or "https://api.tcgdex.net/v2"


def _search_locales(query: str) -> list[str]:
    candidates: list[str]
    if re.search(r"[\u3040-\u30ff]", query):
        candidates = ["ja", "zh-tw", "zh-cn", "en"]
    elif re.search(r"[\u4e00-\u9fff]", query):
        candidates = ["zh-tw", "zh-cn", "ja", "en"]
    else:
        candidates = [settings.tcgdex_locale, "en"]

    locales: list[str] = []
    for locale in candidates:
        normalized = _safe_locale(locale)
        if normalized in SUPPORTED_SEARCH_LOCALES and normalized not in locales:
            locales.append(normalized)
    return locales or [settings.tcgdex_locale]


async def fetch_card(card_id: str, locale: str | None = None) -> CardPayload:
    locale = _safe_locale(locale)
    url = f"{_api_base()}/{locale}/cards/{card_id}"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get(url)

    if response.status_code == 404:
        raise CardNotFoundError(f"Card {card_id} was not found.")
    response.raise_for_status()

    card = response.json()
    pricing = card.get("pricing") if isinstance(card.get("pricing"), dict) else {}
    prices = [*_tcgplayer_prices(pricing), *_cardmarket_prices(pricing)]

    return CardPayload(
        card_id=card.get("id", card_id),
        name=card.get("name", card_id),
        image_url=_image_url(card),
        set_name=_set_name(card),
        rarity=card.get("rarity"),
        raw_json=json.dumps(card, ensure_ascii=True),
        prices=prices,
    )


async def search_cards(query: str, limit: int = 12) -> list[CardSearchResult]:
    query = query.strip()
    if not query:
        return []

    locales = _search_locales(query)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        responses = []
        for locale in locales:
            url = f"{_api_base()}/{locale}/cards"
            response = await client.get(url, params={"name": query})
            if response.status_code == 404:
                continue
            response.raise_for_status()
            responses.append((locale, response.json()))

    results: list[CardSearchResult] = []
    seen: set[tuple[str, str]] = set()
    for locale, cards in responses:
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict) or not card.get("id"):
                continue
            key = (locale, str(card["id"]))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                CardSearchResult(
                    card_id=str(card["id"]),
                    name=str(card.get("name") or card["id"]),
                    image_url=_brief_image_url(card),
                    tcgdex_locale=locale,
                    local_id=str(card["localId"]) if card.get("localId") is not None else None,
                )
            )
            if len(results) >= limit:
                return results
    return results
