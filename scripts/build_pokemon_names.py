"""Regenerate ``app/data/pokemon_names.json`` from PokeAPI's official CSV.

The cross-locale search links cards by Pokemon identity (not literal
translation), e.g. 喷火龙 <-> Charizard <-> リザードン <-> 噴火龍. The source of
truth is PokeAPI's ``pokemon_species_names.csv`` which carries the official
localized species names.

Usage::

    python scripts/build_pokemon_names.py [path/to/pokemon_species_names.csv]

If no path is given, the CSV is downloaded from GitHub.
"""

import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

CSV_URL = (
    "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/"
    "data/v2/csv/pokemon_species_names.csv"
)
# PokeAPI language id -> our TCGdex search locale code.
LANGUAGE_TO_LOCALE = {
    1: "ja",      # ja-hrkt (katakana, matches TCGdex Japanese card names)
    9: "en",
    4: "zh-tw",   # zh-hant
    12: "zh-cn",  # zh-hans
}
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "data" / "pokemon_names.json"


def _read_csv_text(argv: list[str]) -> str:
    if len(argv) > 1:
        return Path(argv[1]).read_text(encoding="utf-8")
    with urllib.request.urlopen(CSV_URL, timeout=60) as response:  # noqa: S310
        return response.read().decode("utf-8")


def build(text: str) -> list[dict[str, str]]:
    by_species: dict[int, dict[str, str]] = {}
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        return []
    for row in reader:
        if len(row) < 3:
            continue
        try:
            species_id = int(row[0])
            language_id = int(row[1])
        except ValueError:
            continue
        locale = LANGUAGE_TO_LOCALE.get(language_id)
        if not locale:
            continue
        name = row[2].strip()
        if name:
            by_species.setdefault(species_id, {})[locale] = name

    entries: list[dict[str, str]] = []
    for species_id in sorted(by_species):
        names = by_species[species_id]
        # Keep entries that can actually bridge locales: an English anchor plus
        # at least one CJK form (the whole point of the feature).
        if "en" in names and any(k in names for k in ("ja", "zh-cn", "zh-tw")):
            entries.append({k: names[k] for k in ("en", "ja", "zh-cn", "zh-tw") if k in names})
    return entries


def main() -> None:
    text = _read_csv_text(sys.argv)
    entries = build(text)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(entries)} entries to {OUTPUT}")


if __name__ == "__main__":
    main()
