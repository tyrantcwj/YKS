"""Bundled Simplified Chinese (国行) card index.

TCGdex's ``zh-cn`` catalog is tiny, so Simplified cards barely show up in
search. This module loads a slim, offline snapshot of the community
PTCG-CHS-Datasets dump (see ``scripts/build_chs_cards.py``) and lets search
surface 国行 cards by their Simplified names, with no network dependency.

Cards from here use a ``chs:<id>`` card_id so the rest of the app can route
fetch/sync to the right provider. They carry no live prices (国行 has no public
price API); users track them via manual CNY entry.
"""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app import settings_store
from app.models import CardPayload, CardSearchResult

logger = logging.getLogger(__name__)

CARD_ID_PREFIX = "chs:"
_DATA_FILE = Path(__file__).resolve().parent / "data" / "chs_cards.json"
# jsDelivr mirrors the GitHub repo's images and is generally reachable from
# mainland China (raw.githubusercontent.com often is not). Overridable via the
# settings page if a user has a faster mirror.
_DEFAULT_IMAGE_BASE = "https://cdn.jsdelivr.net/gh/duanxr/PTCG-CHS-Datasets@main/"


@dataclass(frozen=True)
class _ChsCard:
    chs_id: str
    name: str
    set_code: str
    set_name: str | None
    number: str
    rarity: str
    image_rel: str


@lru_cache(maxsize=1)
def _dataset() -> tuple[list[_ChsCard], dict[str, str]]:
    try:
        raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("CHS dataset missing or invalid: %s", _DATA_FILE, exc_info=True)
        return ([], {})
    sets: dict[str, str] = raw.get("sets", {}) if isinstance(raw, dict) else {}
    cards: list[_ChsCard] = []
    for item in raw.get("cards", []) if isinstance(raw, dict) else []:
        card_id = item.get("id")
        name = (item.get("n") or "").strip()
        if card_id is None or not name:
            continue
        set_code = (item.get("s") or "").strip()
        cards.append(
            _ChsCard(
                chs_id=str(card_id),
                name=name,
                set_code=set_code,
                set_name=sets.get(set_code),
                number=(item.get("no") or "").strip(),
                rarity=(item.get("r") or "").strip(),
                image_rel=(item.get("img") or "").strip(),
            )
        )
    return (cards, sets)


def _image_base() -> str:
    base = (settings_store.get_str("chs_image_base") or _DEFAULT_IMAGE_BASE).strip()
    return (base or _DEFAULT_IMAGE_BASE).rstrip("/") + "/"


def _image_url(card: _ChsCard) -> str | None:
    if not card.image_rel:
        return None
    # Some source rows use Windows-style backslashes; URLs need forward slashes.
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

    scored: list[tuple[int, int, _ChsCard]] = []
    for index, card in enumerate(cards):
        rank = _score(card.name, terms)
        if rank is not None:
            scored.append((rank, index, card))
    scored.sort(key=lambda item: (item[0], item[1]))

    results: list[CardSearchResult] = []
    seen: set[str] = set()
    for _, _, card in scored:
        if card.chs_id in seen:
            continue
        seen.add(card.chs_id)
        results.append(
            CardSearchResult(
                card_id=f"{CARD_ID_PREFIX}{card.chs_id}",
                name=card.name,
                image_url=_image_url(card),
                tcgdex_locale="zh-cn",
                local_id=card.number or None,
            )
        )
        if len(results) >= limit:
            break
    return results


def get_card(card_id: str) -> CardPayload | None:
    raw_id = card_id[len(CARD_ID_PREFIX):] if card_id.startswith(CARD_ID_PREFIX) else card_id
    cards, _ = _dataset()
    match = next((card for card in cards if card.chs_id == raw_id), None)
    if match is None:
        return None
    return CardPayload(
        card_id=card_id,
        name=match.name,
        image_url=_image_url(match),
        set_name=match.set_name or match.set_code or None,
        rarity=match.rarity or None,
        raw_json=json.dumps(
            {
                "id": match.chs_id,
                "name": match.name,
                "set": match.set_name,
                "number": match.number,
                "rarity": match.rarity,
                "source": "PTCG-CHS-Datasets",
            },
            ensure_ascii=True,
        ),
        prices=[],
    )
