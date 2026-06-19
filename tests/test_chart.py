import sqlite3

from app.chart import build_price_chart
from app.db import init_db
from app.models import PricePoint
from app import repository


def test_build_price_chart_uses_selected_variant(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        subscription_id = repository.create_subscription(
            conn,
            card_id="basep-1",
            nickname="Pikachu",
            variant="normal",
            target_price=None,
            alert_percent=None,
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "basep-1",
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=1.0),
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "basep-1",
            PricePoint(provider="tcgplayer", currency="USD", variant="reverse", market_price=99.0),
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "basep-1",
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=2.0),
        )
        conn.commit()
        rows = repository.recent_prices(conn, subscription_id, limit=20)
    finally:
        conn.close()

    chart = build_price_chart(rows, "normal")

    assert chart is not None
    assert chart.count == 2
    assert chart.min_price == 1.0
    assert chart.max_price == 2.0
    assert "99.0" not in chart.points
