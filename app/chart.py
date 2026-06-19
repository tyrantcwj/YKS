import sqlite3
from dataclasses import dataclass

from app.pricing import display_price


@dataclass(frozen=True)
class PriceChart:
    points: str
    min_price: float
    max_price: float
    first_label: str
    last_label: str
    currency: str
    count: int


def build_price_chart(rows: list[sqlite3.Row], variant: str) -> PriceChart | None:
    values: list[tuple[str, float, str]] = []
    for row in reversed(rows):
        if row["variant"] != variant:
            continue
        price = display_price(row)
        if price is None:
            continue
        values.append((row["snapshot_at"], price, row["currency"]))

    if not values:
        return None

    min_price = min(value for _, value, _ in values)
    max_price = max(value for _, value, _ in values)
    price_range = max(max_price - min_price, 1)
    width = 720
    height = 220
    pad = 24
    step = (width - pad * 2) / max(len(values) - 1, 1)

    points: list[str] = []
    for index, (_, value, _) in enumerate(values):
        x = pad + index * step
        normalized = (value - min_price) / price_range
        y = height - pad - normalized * (height - pad * 2)
        points.append(f"{x:.1f},{y:.1f}")

    return PriceChart(
        points=" ".join(points),
        min_price=min_price,
        max_price=max_price,
        first_label=values[0][0],
        last_label=values[-1][0],
        currency=values[-1][2],
        count=len(values),
    )
