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


def _chart_from_values(values: list[tuple[str, float]], currency: str) -> PriceChart | None:
    if not values:
        return None

    prices = [value for _, value in values]
    min_price = min(prices)
    max_price = max(prices)
    price_range = max(max_price - min_price, 1)
    width = 720
    height = 220
    pad = 24
    step = (width - pad * 2) / max(len(values) - 1, 1)

    points: list[str] = []
    for index, (_, value) in enumerate(values):
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
        currency=currency,
        count=len(values),
    )


def build_price_chart(rows: list[sqlite3.Row], variant: str) -> PriceChart | None:
    values: list[tuple[str, float]] = []
    currency = ""
    for row in reversed(rows):
        if row["variant"] != variant:
            continue
        price = display_price(row)
        if price is None:
            continue
        values.append((row["snapshot_at"], price))
        currency = row["currency"]

    return _chart_from_values(values, currency)


def build_trend_chart(rows: list[sqlite3.Row]) -> PriceChart | None:
    """Build a short trend line from Cardmarket 1/7/30-day averages.

    This lets the detail page show a meaningful curve immediately after the
    first sync, before we have collected our own day-over-day history.
    """
    best: sqlite3.Row | None = None
    for row in rows:
        keys = row.keys()
        if "avg30_price" not in keys:
            continue
        has_window = any(
            row[key] is not None for key in ("avg30_price", "avg7_price", "avg1_price")
        )
        if has_window:
            best = row
            break

    if best is None:
        return None

    latest = display_price(best)
    series = [
        ("30日均价", best["avg30_price"]),
        ("7日均价", best["avg7_price"]),
        ("1日均价", best["avg1_price"]),
        ("最新", latest),
    ]
    values = [(label, float(value)) for label, value in series if value is not None]
    if len(values) < 2:
        return None
    return _chart_from_values(values, best["currency"])
