import sqlite3

from app.db import init_db
from app import repository


def test_list_subscriptions_selects_latest_matching_variant(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        subscription_id = repository.create_subscription(
            conn,
            card_id="swsh3-136",
            nickname="Charizard",
            variant="holo",
            target_price=None,
            alert_percent=None,
        )
        conn.execute(
            """
            INSERT INTO price_snapshots (
                subscription_id, card_id, provider, currency, variant, market_price
            )
            VALUES (?, 'swsh3-136', 'tcgplayer', 'USD', 'normal', 1.0)
            """,
            (subscription_id,),
        )
        conn.execute(
            """
            INSERT INTO price_snapshots (
                subscription_id, card_id, provider, currency, variant, market_price
            )
            VALUES (?, 'swsh3-136', 'tcgplayer', 'USD', 'holo', 42.0)
            """,
            (subscription_id,),
        )
        conn.commit()

        rows = repository.list_subscriptions(conn)

        assert len(rows) == 1
        assert rows[0]["variant"] == "holo"
        assert rows[0]["market_price"] == 42.0
    finally:
        conn.close()
