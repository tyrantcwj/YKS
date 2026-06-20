import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app import pokemon_names, settings_store
from app.cardimage import resolve_fallback_image
from app.config import settings
from app.models import CardPayload, CardSearchResult, PricePoint

logger = logging.getLogger(__name__)


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
    base = (settings_store.get_str("tcgdex_api_base") or "https://api.tcgdex.net/v2").strip().rstrip("/")
    return base or "https://api.tcgdex.net/v2"


def _search_locales(query: str) -> list[str]:
    candidates: list[str]
    if re.search(r"[\u3040-\u30ff]", query):
        candidates = ["ja", "zh-cn", "zh-tw", "en"]
    elif re.search(r"[\u4e00-\u9fff]", query):
        # Lead with Simplified so a 简中 user sees zh-cn cards first (its catalog
        # is smaller, so it otherwise loses to the larger zh-tw/ja/en sets).
        candidates = ["zh-cn", "zh-tw", "ja", "en"]
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

    image_url = _image_url(card)
    if image_url is None:
        local_id = card.get("localId")
        image_url = await resolve_fallback_image(
            card.get("name"),
            str(local_id) if local_id is not None else None,
            _set_name(card),
        )

    return CardPayload(
        card_id=card.get("id", card_id),
        name=card.get("name", card_id),
        image_url=image_url,
        set_name=_set_name(card),
        rarity=card.get("rarity"),
        raw_json=json.dumps(card, ensure_ascii=True),
        prices=prices,
    )


def _query_script_locales(query: str) -> set[str]:
    """Locales whose script matches the raw query, where we keep the user's
    exact text so partial searches (``char`` -> Charmander/Charizard,
    ``ピカ`` -> ピカチュウ系) still work. For Han queries we return an empty set
    and let exact-name equality decide, so a Simplified query can still pull the
    Traditional card via its linked name (and vice versa)."""

    if re.search(r"[\u3040-\u30ff]", query):
        return {"ja"}
    if re.search(r"[\u4e00-\u9fff]", query):
        return set()
    return {_safe_locale(settings.tcgdex_locale), "en"}


def _locale_term(locale: str, query: str, translated: dict[str, str], script_locales: set[str]) -> str:
    """Search term for a locale: the linked Pokemon name when known, else the
    raw query. This is what makes a 喷火龙 search also hit ``Charizard`` (en)
    and ``リザードン`` (ja) instead of sending Chinese text to every locale.

    The raw query is preserved for the user's own language/script (and when it
    already equals this locale's name) so partial matches aren't narrowed to a
    single species."""

    name = translated.get(locale)
    if not name or not name.strip():
        return query
    if locale in script_locales:
        return query
    if pokemon_names._normalize(query) == pokemon_names._normalize(name):
        return query
    return name.strip()


async def _fetch_locale(client: httpx.AsyncClient, locale: str, term: str) -> tuple[str, Any] | None:
    # `like:` makes TCGdex do a case-insensitive substring match instead of the
    # near-exact match a bare `name=` performs, which is why partial queries
    # used to "find nothing".
    url = f"{_api_base()}/{locale}/cards"
    try:
        response = await client.get(url, params={"name": f"like:{term}"})
    except httpx.HTTPError:
        logger.debug("Search failed for locale %s", locale, exc_info=True)
        return None
    if response.status_code >= 400:
        return None
    return (locale, response.json())


async def search_cards(query: str, limit: int = 24) -> list[CardSearchResult]:
    query = query.strip()
    if not query:
        return []

    locales = _search_locales(query)
    # Link the query to the same Pokemon across locales (识别物种, 非逐字翻译).
    translated = pokemon_names.localized_names(query)
    script_locales = _query_script_locales(query)
    per_locale = max(limit, 12)

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        fetched = await asyncio.gather(
            *(
                _fetch_locale(client, locale, _locale_term(locale, query, translated, script_locales))
                for locale in locales
            )
        )
    responses: list[tuple[str, Any]] = [item for item in fetched if item is not None]

    # Dedup by card_id (across locales) so the same printing never eats multiple
    # slots, and bucket per locale so we can interleave them below.
    seen: set[str] = set()
    buckets: list[list[CardSearchResult]] = []
    for locale, cards in responses:
        if not isinstance(cards, list):
            continue
        bucket: list[CardSearchResult] = []
        for card in cards:
            if not isinstance(card, dict) or not card.get("id"):
                continue
            card_id = str(card["id"])
            if card_id in seen:
                continue
            seen.add(card_id)
            bucket.append(
                CardSearchResult(
                    card_id=card_id,
                    name=str(card.get("name") or card_id),
                    image_url=_brief_image_url(card),
                    tcgdex_locale=locale,
                    local_id=str(card["localId"]) if card.get("localId") is not None else None,
                )
            )
            if len(bucket) >= per_locale:
                break
        buckets.append(bucket)

    # Interleave locales round-robin (one card per locale per round) so a Chinese
    # search surfaces a 中/英/日 mix instead of being filled by the first locale.
    # Ordering by round *before* image presence is deliberate: zh-cn cards often
    # have no thumbnail on TCGdex, and a global image-first sort would push the
    # few Simplified results past the result limit. Within a round, cards with
    # artwork still come first.
    scored: list[tuple[tuple[int, int, int], CardSearchResult]] = []
    for locale_index, bucket in enumerate(buckets):
        for round_index, result in enumerate(bucket):
            scored.append(((round_index, 0 if result.image_url else 1, locale_index), result))
    scored.sort(key=lambda item: item[0])
    return [result for _, result in scored][:limit]
