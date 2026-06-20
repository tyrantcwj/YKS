import sqlite3

from app.models import CardPayload, PricePoint
from app.psa import PsaCert


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
            latest.snapshot_at,
            history.historical_high,
            pc.grade AS psa_grade
        FROM subscriptions s
        LEFT JOIN cards c ON c.card_id = s.card_id
        LEFT JOIN psa_certs pc ON pc.subscription_id = s.id
        LEFT JOIN (
            SELECT ranked.*
            FROM (
                SELECT
                    ps.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY ps.subscription_id
                        ORDER BY
                            (ps.variant = sub.variant) DESC,
                            ps.snapshot_at DESC,
                            ps.id DESC
                    ) AS _rank
                FROM price_snapshots ps
                JOIN subscriptions sub ON sub.id = ps.subscription_id
                WHERE COALESCE(ps.market_price, ps.trend_price, ps.mid_price, ps.low_price) IS NOT NULL
            ) ranked
            WHERE ranked._rank = 1
        ) latest ON latest.subscription_id = s.id
        LEFT JOIN (
            SELECT
                subscription_id,
                MAX(COALESCE(market_price, trend_price, mid_price, low_price)) AS historical_high
            FROM price_snapshots
            GROUP BY subscription_id
        ) history ON history.subscription_id = s.id
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


def set_sync_error(db: sqlite3.Connection, subscription_id: int, message: str) -> None:
    db.execute(
        "UPDATE subscriptions SET last_sync_error = ? WHERE id = ?",
        (message[:500], subscription_id),
    )


def set_psa_cert_number(db: sqlite3.Connection, subscription_id: int, cert_number: str) -> None:
    db.execute(
        "UPDATE subscriptions SET psa_cert_number = ? WHERE id = ?",
        (cert_number.strip(), subscription_id),
    )


def set_jhs_card_id(db: sqlite3.Connection, subscription_id: int, jhs_card_id: str) -> None:
    db.execute(
        "UPDATE subscriptions SET jhs_card_id = ? WHERE id = ?",
        (jhs_card_id.strip(), subscription_id),
    )


def save_psa_cert(db: sqlite3.Connection, subscription_id: int, cert: PsaCert) -> None:
    db.execute(
        """
        INSERT INTO psa_certs (
            subscription_id, cert_number, grade, subject, year, brand,
            card_number, variety, spec_id, population_total, population_higher,
            fetched_at, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(subscription_id) DO UPDATE SET
            cert_number = excluded.cert_number,
            grade = excluded.grade,
            subject = excluded.subject,
            year = excluded.year,
            brand = excluded.brand,
            card_number = excluded.card_number,
            variety = excluded.variety,
            spec_id = excluded.spec_id,
            population_total = excluded.population_total,
            population_higher = excluded.population_higher,
            fetched_at = CURRENT_TIMESTAMP,
            raw_json = excluded.raw_json
        """,
        (
            subscription_id,
            cert.cert_number,
            cert.grade,
            cert.subject,
            cert.year,
            cert.brand,
            cert.card_number,
            cert.variety,
            cert.spec_id,
            cert.population_total,
            cert.population_higher,
            cert.raw_json,
        ),
    )


def get_psa_cert(db: sqlite3.Connection, subscription_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM psa_certs WHERE subscription_id = ?",
        (subscription_id,),
    ).fetchone()


def delete_psa_cert(db: sqlite3.Connection, subscription_id: int) -> None:
    db.execute("DELETE FROM psa_certs WHERE subscription_id = ?", (subscription_id,))


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
            low_price, mid_price, high_price, direct_price, trend_price,
            avg1_price, avg7_price, avg30_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            price.avg1_price,
            price.avg7_price,
            price.avg30_price,
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


def provider_market_stats(db: sqlite3.Connection, subscription_id: int) -> list[sqlite3.Row]:
    return db.execute(
        """
        WITH priced AS (
            SELECT
                ps.*,
                COALESCE(ps.market_price, ps.trend_price, ps.mid_price, ps.low_price) AS display_price
            FROM price_snapshots ps
            WHERE ps.subscription_id = ?
        ),
        latest AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY provider, currency, variant
                    ORDER BY snapshot_at DESC, id DESC
                ) AS rank
            FROM priced
            WHERE display_price IS NOT NULL
        )
        SELECT
            p.provider,
            p.currency,
            p.variant,
            COUNT(p.display_price) AS sample_count,
            MIN(p.display_price) AS low_price,
            MAX(p.display_price) AS high_price,
            AVG(p.display_price) AS average_price,
            l.display_price AS latest_price,
            l.snapshot_at AS latest_snapshot_at
        FROM priced p
        JOIN latest l ON l.provider = p.provider
            AND l.currency = p.currency
            AND l.variant = p.variant
            AND l.rank = 1
        WHERE p.display_price IS NOT NULL
        GROUP BY p.provider, p.currency, p.variant
        ORDER BY
            CASE p.provider
                WHEN 'snkrdunk' THEN 0
                WHEN 'ebay' THEN 1
                WHEN 'manual' THEN 2
                WHEN 'tcgplayer' THEN 3
                WHEN 'cardmarket' THEN 4
                ELSE 5
            END,
            p.variant,
            p.currency
        """,
        (subscription_id,),
    ).fetchall()


def market_summary(db: sqlite3.Connection) -> sqlite3.Row:
    return db.execute(
        """
        WITH latest AS (
            SELECT
                s.id,
                ps.currency,
                COALESCE(ps.market_price, ps.trend_price, ps.mid_price, ps.low_price) AS display_price
            FROM subscriptions s
            LEFT JOIN price_snapshots ps ON ps.id = (
                SELECT inner_ps.id
                FROM price_snapshots inner_ps
                WHERE inner_ps.subscription_id = s.id
                  AND inner_ps.variant = s.variant
                ORDER BY inner_ps.snapshot_at DESC, inner_ps.id DESC
                LIMIT 1
            )
        )
        SELECT
            (SELECT COUNT(*) FROM subscriptions) AS total_subscriptions,
            (SELECT COUNT(*) FROM subscriptions WHERE active = 1) AS active_subscriptions,
            (SELECT COUNT(*) FROM latest WHERE display_price IS NOT NULL) AS priced_subscriptions,
            (SELECT COUNT(*) FROM price_snapshots) AS price_snapshots,
            (SELECT MAX(display_price) FROM latest) AS highest_price,
            (
                SELECT currency
                FROM latest
                WHERE display_price IS NOT NULL
                ORDER BY display_price DESC
                LIMIT 1
            ) AS highest_currency,
            (SELECT MAX(last_synced_at) FROM cards) AS last_synced_at
        """
    ).fetchone()


def recent_price_movements(db: sqlite3.Connection, limit: int = 6) -> list[sqlite3.Row]:
    return db.execute(
        """
        WITH ranked AS (
            SELECT
                ps.*,
                COALESCE(ps.market_price, ps.trend_price, ps.mid_price, ps.low_price) AS display_price,
                ROW_NUMBER() OVER (
                    PARTITION BY ps.subscription_id, ps.variant
                    ORDER BY ps.snapshot_at DESC, ps.id DESC
                ) AS rank
            FROM price_snapshots ps
        ),
        latest AS (
            SELECT * FROM ranked WHERE rank = 1 AND display_price IS NOT NULL
        ),
        previous AS (
            SELECT * FROM ranked WHERE rank = 2 AND display_price IS NOT NULL
        )
        SELECT
            s.id AS subscription_id,
            s.card_id,
            COALESCE(NULLIF(s.nickname, ''), c.name, s.card_id) AS title,
            c.image_url,
            c.set_name,
            c.rarity,
            latest.provider,
            latest.currency,
            latest.variant,
            latest.display_price AS latest_price,
            previous.display_price AS previous_price,
            latest.snapshot_at,
            CASE
                WHEN previous.display_price IS NULL OR previous.display_price = 0 THEN NULL
                ELSE ((latest.display_price - previous.display_price) / previous.display_price) * 100
            END AS change_percent
        FROM latest
        JOIN subscriptions s ON s.id = latest.subscription_id
        LEFT JOIN previous ON previous.subscription_id = latest.subscription_id
            AND previous.variant = latest.variant
        LEFT JOIN cards c ON c.card_id = latest.card_id
        ORDER BY
            CASE WHEN previous.display_price IS NULL THEN 1 ELSE 0 END,
            ABS(COALESCE(change_percent, 0)) DESC,
            latest.snapshot_at DESC,
            latest.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def ranked_cards(db: sqlite3.Connection, limit: int = 8) -> list[sqlite3.Row]:
    return db.execute(
        """
        WITH prices AS (
            SELECT
                ps.subscription_id,
                ps.variant,
                COALESCE(ps.market_price, ps.trend_price, ps.mid_price, ps.low_price) AS display_price
            FROM price_snapshots ps
        ),
        ranked AS (
            SELECT
                s.id AS subscription_id,
                s.card_id,
                COALESCE(NULLIF(s.nickname, ''), c.name, s.card_id) AS title,
                c.image_url,
                c.set_name,
                c.rarity,
                s.variant,
                latest.currency,
                latest.display_price AS latest_price,
                MAX(prices.display_price) AS historical_high,
                COUNT(prices.display_price) AS sample_count
            FROM subscriptions s
            LEFT JOIN cards c ON c.card_id = s.card_id
            LEFT JOIN prices ON prices.subscription_id = s.id
                AND prices.variant = s.variant
                AND prices.display_price IS NOT NULL
            LEFT JOIN (
                SELECT
                    ps.subscription_id,
                    ps.variant,
                    ps.currency,
                    COALESCE(ps.market_price, ps.trend_price, ps.mid_price, ps.low_price) AS display_price,
                    ROW_NUMBER() OVER (
                        PARTITION BY ps.subscription_id, ps.variant
                        ORDER BY ps.snapshot_at DESC, ps.id DESC
                    ) AS rank
                FROM price_snapshots ps
            ) latest ON latest.subscription_id = s.id
                AND latest.variant = s.variant
                AND latest.rank = 1
            GROUP BY s.id
        )
        SELECT *
        FROM ranked
        ORDER BY
            CASE WHEN historical_high IS NULL THEN 1 ELSE 0 END,
            historical_high DESC,
            sample_count DESC,
            title COLLATE NOCASE ASC
        LIMIT ?
        """,
        (limit,),
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
