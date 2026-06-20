"""Bundled official Japanese card index.

TCGdex only localizes a small slice of Japanese cards (e.g. 25 リザードン vs the
official ~86), so the 日文 search filter looked far emptier than marketplaces
like 集换社. This module loads a slim, offline snapshot scraped from the official
pokemon-card.com search (community project type-null/PTCG-database, see
``scripts/build_ja_cards.py``) and surfaces those cards by their Japanese names
with no network dependency.

Cards from here use a ``jp:<id>`` card_id so the rest of the app can route
fetch/sync correctly. They carry no live prices (the official site has none),
so users track them via manual JPY entry. They are tagged ``ja`` so they share
the 日文 filter with TCGdex's Japanese results.
"""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app import settings_store
from app.models import CardPayload, CardSearchResult

logger = logging.getLogger(__name__)

CARD_ID_PREFIX = "jp:"
_DATA_FILE = Path(__file__).resolve().parent / "data" / "ja_cards.json"
_DEFAULT_IMAGE_BASE = "https://www.pokemon-card.com/"


@dataclass(frozen=True)
class _JaCard:
    jp_id: str
    name: str
    set_name: str
    number: str
    card_type: str
    image_rel: str


@lru_cache(maxsize=1)
def _dataset() -> tuple[list[_JaCard], str]:
    try:
        raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("JA dataset missing or invalid: %s", _DATA_FILE, exc_info=True)
        return ([], _DEFAULT_IMAGE_BASE)
    if not isinstance(raw, dict):
        return ([], _DEFAULT_IMAGE_BASE)
    base = (raw.get("image_base") or _DEFAULT_IMAGE_BASE).strip() or _DEFAULT_IMAGE_BASE
    cards: list[_JaCard] = []
    for item in raw.get("cards", []):
        card_id = item.get("id")
        name = (item.get("n") or "").strip()
        if card_id is None or not name:
            continue
        cards.append(
            _JaCard(
                jp_id=str(card_id),
                name=name,
                set_name=(item.get("set") or "").strip(),
                number=(item.get("no") or "").strip(),
                card_type=(item.get("t") or "").strip(),
                image_rel=(item.get("img") or "").strip(),
            )
        )
    return (cards, base)


def _image_base() -> str:
    _, bundled_base = _dataset()
    base = (settings_store.get_str("ja_image_base") or bundled_base).strip()
    return (base or bundled_base).rstrip("/") + "/"


def _image_url(card: _JaCard) -> str | None:
    if not card.image_rel:
        return None
    rel = card.image_rel.replace("\\", "/").lstrip("/")
    return f"{_image_base()}{rel}"


def _score(name: str, terms: list[str]) -> int | None:
    """Lower is better: 0 exact, 1 prefix, 2 substring, None no match."""

    best: int | None = None
    for term in terms:
        if not term:
            continue
        if name == term:
            return 0
        if name.startswith(term):
            best = 1 if best is None else min(best, 1)
        elif term in name:
            best = 2 if best is None else min(best, 2)
    return best


def search(query: str, limit: int = 24, extra_terms: list[str] | None = None) -> list[CardSearchResult]:
    query = (query or "").strip()
    terms = [t for t in [query, *(extra_terms or [])] if t and t.strip()]
    if not terms:
        return []
    cards, _ = _dataset()
    if not cards:
        return []

    scored: list[tuple[int, int, _JaCard]] = []
    for index, card in enumerate(cards):
        rank = _score(card.name, terms)
        if rank is not None:
            scored.append((rank, index, card))
    scored.sort(key=lambda item: (item[0], item[1]))

    results: list[CardSearchResult] = []
    seen: set[str] = set()
    for _, _, card in scored:
        if card.jp_id in seen:
            continue
        seen.add(card.jp_id)
        results.append(
            CardSearchResult(
                card_id=f"{CARD_ID_PREFIX}{card.jp_id}",
                name=card.name,
                image_url=_image_url(card),
                tcgdex_locale="ja",
                local_id=card.number or None,
            )
        )
        if len(results) >= limit:
            break
    return results


def get_card(card_id: str) -> CardPayload | None:
    raw_id = card_id[len(CARD_ID_PREFIX):] if card_id.startswith(CARD_ID_PREFIX) else card_id
    cards, _ = _dataset()
    match = next((card for card in cards if card.jp_id == raw_id), None)
    if match is None:
        return None
    return CardPayload(
        card_id=card_id,
        name=match.name,
        image_url=_image_url(match),
        set_name=match.set_name or None,
        rarity=match.card_type or None,
        raw_json=json.dumps(
            {
                "id": match.jp_id,
                "name": match.name,
                "set": match.set_name,
                "number": match.number,
                "card_type": match.card_type,
                "source": "pokemon-card.com (type-null/PTCG-database)",
            },
            ensure_ascii=True,
        ),
        prices=[],
    )
