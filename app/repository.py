import sqlite3

from app.models import CardPayload, PricePoint


def list_subscriptions(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT
            s.*,
            c.name,
            c.image_url,
            c.set_name,
            c.rarity,
            c.last_synced_at,
            latest.provider,
            latest.currency,
            latest.market_price,
            latest.low_price,
            latest.mid_price,
            latest.high_price,
            latest.direct_price,
            latest.trend_price,
            latest.snapshot_at
        FROM subscriptions s
        LEFT JOIN cards c ON c.card_id = s.card_id
        LEFT JOIN price_snapshots latest ON latest.id = (
            SELECT ps.id
            FROM price_snapshots ps
            WHERE ps.subscription_id = s.id
              AND ps.variant = s.variant
            ORDER BY
                ps.snapshot_at DESC,
                ps.id DESC
            LIMIT 1
        )
        ORDER BY s.active DESC, s.updated_at DESC, s.id DESC
        """
    ).fetchall()


def create_subscription(
    db: sqlite3.Connection,
    card_id: str,
    nickname: str,
    variant: str,
    target_price: float | None,
    alert_percent: float | None,
    tcgdex_locale: str = "",
) -> int:
    cursor = db.execute(
        """
        INSERT INTO subscriptions (card_id, nickname, variant, target_price, alert_percent, tcgdex_locale)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(card_id) DO UPDATE SET
            nickname = excluded.nickname,
            variant = excluded.variant,
            tcgdex_locale = excluded.tcgdex_locale,
            target_price = excluded.target_price,
            alert_percent = excluded.alert_percent,
            active = 1,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (card_id, nickname, variant, target_price, alert_percent, tcgdex_locale),
    )
    return int(cursor.fetchone()["id"])


def update_subscription(
    db: sqlite3.Connection,
    subscription_id: int,
    nickname: str,
    variant: str,
    target_price: float | None,
    alert_percent: float | None,
    active: bool,
) -> None:
    db.execute(
        """
        UPDATE subscriptions
        SET nickname = ?, variant = ?, target_price = ?, alert_percent = ?,
            active = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (nickname, variant, target_price, alert_percent, int(active), subscription_id),
    )


def delete_subscription(db: sqlite3.Connection, subscription_id: int) -> None:
    db.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))


def get_subscription(db: sqlite3.Connection, subscription_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT
            s.*,
            c.name,
            c.image_url,
            c.set_name,
            c.rarity,
            c.last_synced_at
        FROM subscriptions s
        LEFT JOIN cards c ON c.card_id = s.card_id
        WHERE s.id = ?
        """,
        (subscription_id,),
    ).fetchone()


def active_subscriptions(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM subscriptions WHERE active = 1 ORDER BY id").fetchall()


def save_card_payload(db: sqlite3.Connection, subscription_id: int, payload: CardPayload) -> None:
    db.execute(
        """
        INSERT INTO cards (card_id, name, image_url, set_name, rarity, last_synced_at, raw_json)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(card_id) DO UPDATE SET
            name = excluded.name,
            image_url = excluded.image_url,
            set_name = excluded.set_name,
            rarity = excluded.rarity,
            last_synced_at = CURRENT_TIMESTAMP,
            raw_json = excluded.raw_json
        """,
        (
            payload.card_id,
            payload.name,
            payload.image_url,
            payload.set_name,
            payload.rarity,
            payload.raw_json,
        ),
    )
    for price in payload.prices:
        save_price_snapshot(db, subscription_id, payload.card_id, price)


def save_price_snapshot(
    db: sqlite3.Connection,
    subscription_id: int,
    card_id: str,
    price: PricePoint,
) -> None:
    db.execute(
        """
        INSERT INTO price_snapshots (
            subscription_id, card_id, provider, currency, variant, market_price,
            low_price, mid_price, high_price, direct_price, trend_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subscription_id,
            card_id,
            price.provider,
            price.currency,
            price.variant,
            price.market_price,
            price.low_price,
            price.mid_price,
            price.high_price,
            price.direct_price,
            price.trend_price,
        ),
    )


def recent_prices(db: sqlite3.Connection, subscription_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT *
        FROM price_snapshots
        WHERE subscription_id = ?
        ORDER BY snapshot_at DESC, id DESC
        LIMIT ?
        """,
        (subscription_id, limit),
    ).fetchall()


def latest_price_for_variant(
    db: sqlite3.Connection,
    subscription_id: int,
    variant: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT *
        FROM price_snapshots
        WHERE subscription_id = ? AND variant = ?
        ORDER BY snapshot_at DESC, id DESC
        LIMIT 1
        """,
        (subscription_id, variant),
    ).fetchone()


def previous_price_for_variant(
    db: sqlite3.Connection,
    subscription_id: int,
    variant: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT *
        FROM price_snapshots
        WHERE subscription_id = ? AND variant = ?
        ORDER BY snapshot_at DESC, id DESC
        LIMIT 1 OFFSET 1
        """,
        (subscription_id, variant),
    ).fetchone()


def latest_prices_by_subscription(db: sqlite3.Connection, subscription_id: int) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT ps.*
        FROM price_snapshots ps
        JOIN (
            SELECT provider, currency, variant, MAX(id) AS latest_id
            FROM price_snapshots
            WHERE subscription_id = ?
            GROUP BY provider, currency, variant
        ) latest ON latest.latest_id = ps.id
        ORDER BY
            CASE ps.provider
                WHEN 'tcgplayer' THEN 0
                WHEN 'cardmarket' THEN 1
                ELSE 2
            END,
            ps.variant
        """,
        (subscription_id,),
    ).fetchall()


def create_alert(db: sqlite3.Connection, subscription_id: int, kind: str, message: str) -> None:
    db.execute(
        "INSERT INTO alerts (subscription_id, kind, message) VALUES (?, ?, ?)",
        (subscription_id, kind, message),
    )


def list_alerts(db: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT a.*, s.card_id, COALESCE(NULLIF(s.nickname, ''), c.name, s.card_id) AS title
        FROM alerts a
        JOIN subscriptions s ON s.id = a.subscription_id
        LEFT JOIN cards c ON c.card_id = s.card_id
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def export_subscriptions(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT
            s.id,
            s.card_id,
            COALESCE(NULLIF(s.nickname, ''), c.name, s.card_id) AS title,
            s.nickname,
            s.variant,
            s.tcgdex_locale,
            s.target_price,
            s.alert_percent,
            s.active,
            c.name,
            c.set_name,
            c.rarity,
            c.last_synced_at,
            s.created_at,
            s.updated_at
        FROM subscriptions s
        LEFT JOIN cards c ON c.card_id = s.card_id
        ORDER BY s.id
        """
    ).fetchall()


def export_price_snapshots(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT
            ps.id,
            ps.subscription_id,
            ps.card_id,
            COALESCE(NULLIF(s.nickname, ''), c.name, ps.card_id) AS title,
            ps.provider,
            ps.currency,
            ps.variant,
            ps.market_price,
            ps.low_price,
            ps.mid_price,
            ps.high_price,
            ps.direct_price,
            ps.trend_price,
            ps.snapshot_at
        FROM price_snapshots ps
        LEFT JOIN subscriptions s ON s.id = ps.subscription_id
        LEFT JOIN cards c ON c.card_id = ps.card_id
        ORDER BY ps.snapshot_at DESC, ps.id DESC
        """
    ).fetchall()
