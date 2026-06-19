import sqlite3

from app import repository
from app.db import init_db
from app.models import PricePoint
from app.pricing import _alert_for_thresholds


def _latest(conn: sqlite3.Connection, subscription_id: int):
    return repository.latest_price_for_variant(conn, subscription_id, "normal")


def _previous(conn: sqlite3.Connection, subscription_id: int):
    return repository.previous_price_for_variant(conn, subscription_id, "normal")


def test_target_alert_only_fires_when_crossing_threshold(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        subscription_id = repository.create_subscription(
            conn,
            card_id="swsh3-136",
            nickname="Furret",
            variant="normal",
            target_price=5.0,
            alert_percent=None,
        )
        subscription = repository.get_subscription(conn, subscription_id)

        repository.save_price_snapshot(
            conn,
            subscription_id,
            "swsh3-136",
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=4.0),
        )
        notifications = _alert_for_thresholds(
            conn,
            subscription,
            _latest(conn, subscription_id),
            _previous(conn, subscription_id),
        )
        assert len(repository.list_alerts(conn)) == 1
        assert len(notifications) == 1

        repository.save_price_snapshot(
            conn,
            subscription_id,
            "swsh3-136",
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=4.0),
        )
        notifications = _alert_for_thresholds(
            conn,
            subscription,
            _latest(conn, subscription_id),
            _previous(conn, subscription_id),
        )
        assert len(repository.list_alerts(conn)) == 1
        assert notifications == []

        repository.save_price_snapshot(
            conn,
            subscription_id,
            "swsh3-136",
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=6.0),
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "swsh3-136",
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=4.5),
        )
        notifications = _alert_for_thresholds(
            conn,
            subscription,
            _latest(conn, subscription_id),
            _previous(conn, subscription_id),
        )
        assert len(repository.list_alerts(conn)) == 2
        assert len(notifications) == 1
    finally:
        conn.close()
