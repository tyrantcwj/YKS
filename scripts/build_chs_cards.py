"""Slim the PTCG-CHS-Datasets dump into a compact bundled card index.

Source: https://github.com/duanxr/PTCG-CHS-Datasets (``ptcg_chs_infos.json``,
~22MB). We only need enough to *search and display* Simplified Chinese cards,
so we drop ability text / pokedex blurbs / dimensions and keep name, set,
collection number, rarity and the relative image path.

Usage::

    python scripts/build_chs_cards.py path/to/ptcg_chs_infos.json

Output: ``app/data/chs_cards.json`` with shape::

    {"sets": {"CSV9C": "补充包 星彩晶璃", ...},
     "cards": [{"id": 18571, "n": "蛋蛋", "s": "CSV9C",
                "no": "001/208", "r": "C", "img": "img/475/0.png"}, ...]}
"""

import json
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/duanxr/PTCG-CHS-Datasets/main/ptcg_chs_infos.json"
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "data" / "chs_cards.json"


def _load_source(argv: list[str]) -> dict:
    if len(argv) > 1:
        return json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def build(source: dict) -> dict:
    collections = source.get("collections", [])
    sets: dict[str, str] = {}
    cards: list[dict] = []
    for collection in collections:
        code = (collection.get("commodityCode") or "").strip()
        name = (collection.get("name") or "").strip()
        if code and name:
            sets[code] = name
        for card in collection.get("cards", []):
            card_name = (card.get("name") or "").strip()
            if not card_name:
                continue
            details = card.get("details") or {}
            cards.append(
                {
                    "id": card.get("id"),
                    "n": card_name,
                    "s": (card.get("commodityCode") or code or "").strip(),
                    "no": (details.get("collectionNumber") or "").strip(),
                    "r": (details.get("rarityText") or "").strip(),
                    "img": (card.get("image") or "").strip().replace("\\", "/"),
                }
            )
    return {"sets": sets, "cards": cards}


def main() -> None:
    source = _load_source(sys.argv)
    data = build(source)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(data['cards'])} cards / {len(data['sets'])} sets to {OUTPUT}")


if __name__ == "__main__":
    main()
