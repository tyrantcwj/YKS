"""Provider-aware card lookup and unified search.

A subscription's ``card_id`` carries a provider prefix so we know where to
fetch metadata/prices from:

* ``chs:<id>``  – bundled Simplified Chinese dataset (:mod:`app.chs`), no prices
* ``pika:<id>`` – PikaQian online API (:mod:`app.pikaqian`), metadata + prices
* anything else – TCGdex (:mod:`app.tcgdex`), the default

Search merges all three sources, interleaved so Simplified cards are visible
for Chinese queries instead of being crowded out by TCGdex's larger zh-tw/en/ja
catalogs.
"""

import re

from app import chs, pikaqian, pokemon_names
from app.models import CardPayload, CardSearchResult
from app.tcgdex import CardNotFoundError, fetch_card as fetch_tcgdex_card, search_cards as search_tcgdex


async def fetch_card_payload(card_id: str, locale: str | None = None) -> CardPayload:
    """Fetch a card from whichever provider its id points at."""

    if card_id.startswith(chs.CARD_ID_PREFIX):
        payload = chs.get_card(card_id)
        if payload is None:
            raise CardNotFoundError(f"国行卡库找不到 {card_id}")
        return payload
    if card_id.startswith(pikaqian.CARD_ID_PREFIX):
        payload = await pikaqian.fetch_card(card_id)
        if payload is None:
            raise CardNotFoundError(f"PikaQian 找不到 {card_id}（确认已在设置页填写 API Key）")
        return payload
    return await fetch_tcgdex_card(card_id, locale)


def _is_chinese(query: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", query))


def _interleave(buckets: list[list[CardSearchResult]], limit: int) -> list[CardSearchResult]:
    # Key by (locale, card_id): the same TCGdex id can appear under several
    # locales (different localized names) and we want each language kept.
    seen: set[tuple[str, str]] = set()
    ordered: list[CardSearchResult] = []
    depth = max((len(bucket) for bucket in buckets), default=0)
    for index in range(depth):
        for bucket in buckets:
            if index >= len(bucket):
                continue
            result = bucket[index]
            key = (result.tcgdex_locale, result.card_id)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(result)
            if len(ordered) >= limit:
                return ordered
    return ordered


# No user-facing result cap (the UI filters instead); this is just a guard so a
# pathological one-character query can't try to materialize the whole catalog.
_SAFETY_CAP = 2000


async def search_all(query: str, limit: int | None = None) -> list[CardSearchResult]:
    query = (query or "").strip()
    if not query:
        return []

    cap = limit if limit is not None else _SAFETY_CAP
    translated = pokemon_names.localized_names(query)
    tcg_results = await search_tcgdex(query, cap)

    chs_extra = [t for t in [translated.get("zh-cn"), translated.get("zh-tw")] if t]
    chs_results = chs.search(query, cap, extra_terms=chs_extra)
    pika_results = await pikaqian.search(query, translated.get("en"), min(cap, 50))

    # Lead with Simplified sources for Chinese queries so 国行 cards surface;
    # otherwise keep TCGdex first.
    if _is_chinese(query):
        buckets = [chs_results, pika_results, tcg_results]
    else:
        buckets = [tcg_results, chs_results, pika_results]
    return _interleave(buckets, cap)
