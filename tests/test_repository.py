import sqlite3

from app.db import init_db
from app import repository
from app.models import CardPayload, PricePoint


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


def test_market_summary_and_recent_price_movements(tmp_path, monkeypatch):
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
        repository.save_card_payload(
            conn,
            subscription_id,
            CardPayload(
                card_id="basep-1",
                name="Pikachu",
                set_name="Promo",
                rarity="promo",
                image_url="https://example.test/pikachu.webp",
                raw_json="{}",
                prices=[],
            ),
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "basep-1",
            PricePoint(provider="manual", currency="JPY", variant="normal", market_price=100.0),
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "basep-1",
            PricePoint(provider="manual", currency="JPY", variant="normal", market_price=125.0),
        )
        conn.commit()

        summary = repository.market_summary(conn)
        movements = repository.recent_price_movements(conn)

        assert summary["total_subscriptions"] == 1
        assert summary["priced_subscriptions"] == 1
        assert summary["price_snapshots"] == 2
        assert summary["highest_price"] == 125.0
        assert summary["highest_currency"] == "JPY"

        assert len(movements) == 1
        assert movements[0]["title"] == "Pikachu"
        assert movements[0]["latest_price"] == 125.0
        assert movements[0]["previous_price"] == 100.0
        assert movements[0]["change_percent"] == 25.0

        ranked = repository.ranked_cards(conn)
        assert len(ranked) == 1
        assert ranked[0]["title"] == "Pikachu"
        assert ranked[0]["historical_high"] == 125.0
        assert ranked[0]["sample_count"] == 2
    finally:
        conn.close()
