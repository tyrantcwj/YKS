"""Slim the type-null/PTCG-database Japanese dump into a bundled card index.

Source: https://github.com/type-null/PTCG-database (``data_jp/*.json``, scraped
from the official https://www.pokemon-card.com card search). TCGdex only
localizes a small slice of Japanese cards (e.g. 25 リザードン vs the official
~86), so we bundle this fuller offline snapshot to back the 日文 search filter.

We only need enough to *search and display* cards, so we keep the Japanese
name, official image, set name, collection number and card type, and drop the
rest (sources/links/etc.).

Usage::

    # point at a local clone's data_jp directory (recommended; the repo holds
    # ~22k card files which are slow to fetch individually over the API):
    python scripts/build_ja_cards.py path/to/PTCG-database/data_jp

Output: ``app/data/ja_cards.json`` with shape::

    {"image_base": "https://www.pokemon-card.com/",
     "cards": [{"id": 37742, "n": "基本草エネルギー",
                "img": "assets/images/card_images/large//037742_E_...jpg",
                "set": "...", "no": "GRA", "t": "基本エネルギー"}, ...]}
"""

import json
import sys
from pathlib import Path

IMAGE_BASE = "https://www.pokemon-card.com/"
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "data" / "ja_cards.json"


def _rel_image(img: str) -> str:
    img = (img or "").strip()
    if img.startswith(IMAGE_BASE):
        return img[len(IMAGE_BASE):]
    for scheme in ("https://", "http://"):
        if img.startswith(scheme):
            # Strip any host and keep the path so a custom base can be applied.
            return img[len(scheme):].split("/", 1)[1] if "/" in img[len(scheme):] else ""
    return img.lstrip("/")


def build(src_dir: Path) -> dict:
    cards: list[dict] = []
    seen: set[int] = set()
    for path in sorted(src_dir.rglob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"), strict=False)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(card, dict):
            continue
        jp_id = card.get("jp_id")
        name = (card.get("name") or "").strip()
        if jp_id is None or not name:
            continue
        try:
            jp_id = int(jp_id)
        except (TypeError, ValueError):
            continue
        if jp_id in seen:
            continue
        seen.add(jp_id)
        cards.append(
            {
                "id": jp_id,
                "n": name,
                "img": _rel_image(card.get("img") or ""),
                "set": (card.get("set_name") or "").strip(),
                "no": (card.get("number") or "").strip(),
                "t": (card.get("card_type") or "").strip(),
            }
        )
    cards.sort(key=lambda c: c["id"])
    return {"image_base": IMAGE_BASE, "cards": cards}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/build_ja_cards.py path/to/PTCG-database/data_jp")
    src_dir = Path(sys.argv[1])
    if not src_dir.is_dir():
        raise SystemExit(f"not a directory: {src_dir}")
    data = build(src_dir)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(data['cards'])} cards to {OUTPUT}")


if __name__ == "__main__":
    main()
