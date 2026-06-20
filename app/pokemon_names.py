"""Cross-locale Pokemon name linking for search.

A Chinese query like ``喷火龙`` should also pull the same Pokemon in other
locales (``Charizard`` / ``リザードン`` / ``噴火龍``). This is identity linking,
*not* literal translation: the names come from PokeAPI's official localized
species names (see ``scripts/build_pokemon_names.py``), so 喷火龙 maps to the
real card name ``Charizard`` rather than a word-for-word rendering.

The dataset is bundled as ``app/data/pokemon_names.json`` and indexed by a
normalized form of every localized name, so a query in any supported locale
resolves to the same entry.
"""

import json
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).resolve().parent / "data" / "pokemon_names.json"
SUPPORTED_LOCALES = ("en", "ja", "zh-tw", "zh-cn")


def _normalize(text: str) -> str:
    # NFKC folds full/half-width kana and casefold handles Latin case so that
    # "Charizard", "charizard" and full-width variants all collapse together.
    return unicodedata.normalize("NFKC", text).strip().casefold()


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[str, str]]:
    """Map ``normalized name -> {locale: name}`` for every localized form."""

    try:
        entries = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Pokemon name dataset missing or invalid: %s", _DATA_FILE, exc_info=True)
        return {}

    index: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        names = {loc: entry[loc] for loc in SUPPORTED_LOCALES if entry.get(loc)}
        for name in names.values():
            key = _normalize(name)
            # First writer wins; the dataset is ordered by national dex number
            # so lower-numbered species take precedence on the rare collision.
            index.setdefault(key, names)
    return index


def localized_names(query: str) -> dict[str, str]:
    """Return per-locale names for the Pokemon a query refers to.

    Matching is, in order: exact name, a species name contained in the query
    (e.g. ``喷火龙ex`` -> Charizard), then the query as a prefix/substring of a
    species name (e.g. ``喷火`` -> Charizard). Returns ``{}`` when nothing
    matches, so callers fall back to the raw query unchanged.
    """

    normalized = _normalize(query)
    if not normalized:
        return {}

    index = _index()
    exact = index.get(normalized)
    if exact is not None:
        return dict(exact)

    if len(normalized) < 2:
        return {}

    # A species name fully contained in the query (longest wins, so "Charizard"
    # beats a shorter incidental match).
    best_len = 0
    best: dict[str, str] | None = None
    for key, names in index.items():
        if len(key) >= 2 and key in normalized and len(key) > best_len:
            best_len = len(key)
            best = names
    if best is not None:
        return dict(best)

    # The query as a partial of a species name ("喷火" -> "喷火龙").
    for key, names in index.items():
        if normalized in key:
            return dict(names)

    return {}
