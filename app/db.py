import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings


def _connect() -> sqlite3.Connection:
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL UNIQUE,
                nickname TEXT NOT NULL DEFAULT '',
                variant TEXT NOT NULL DEFAULT 'holo',
                tcgdex_locale TEXT NOT NULL DEFAULT '',
                target_price REAL,
                alert_percent REAL,
                active INTEGER NOT NULL DEFAULT 1,
                last_sync_error TEXT NOT NULL DEFAULT '',
                psa_cert_number TEXT NOT NULL DEFAULT '',
                jhs_card_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cards (
                card_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                image_url TEXT,
                set_name TEXT,
                rarity TEXT,
                last_synced_at TEXT,
                raw_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                card_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                currency TEXT NOT NULL,
                variant TEXT NOT NULL,
                market_price REAL,
                low_price REAL,
                mid_price REAL,
                high_price REAL,
                direct_price REAL,
                trend_price REAL,
                avg1_price REAL,
                avg7_price REAL,
                avg30_price REAL,
                snapshot_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_card_time
            ON price_snapshots(card_id, snapshot_at DESC);

            CREATE INDEX IF NOT EXISTS idx_snapshots_subscription_time
            ON price_snapshots(subscription_id, snapshot_at DESC);

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                seen INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS psa_certs (
                subscription_id INTEGER PRIMARY KEY,
                cert_number TEXT NOT NULL,
                grade TEXT,
                subject TEXT,
                year TEXT,
                brand TEXT,
                card_number TEXT,
                variety TEXT,
                spec_id TEXT,
                population_total INTEGER,
                population_higher INTEGER,
                fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                raw_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
            );
            """
        )
        _ensure_subscription_columns(db)
        _ensure_snapshot_columns(db)


def backup_database(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as source:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()


def _ensure_subscription_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()
    }
    migrations = {
        "nickname": "ALTER TABLE subscriptions ADD COLUMN nickname TEXT NOT NULL DEFAULT ''",
        "variant": "ALTER TABLE subscriptions ADD COLUMN variant TEXT NOT NULL DEFAULT 'holo'",
        "tcgdex_locale": "ALTER TABLE subscriptions ADD COLUMN tcgdex_locale TEXT NOT NULL DEFAULT ''",
        "target_price": "ALTER TABLE subscriptions ADD COLUMN target_price REAL",
        "alert_percent": "ALTER TABLE subscriptions ADD COLUMN alert_percent REAL",
        "active": "ALTER TABLE subscriptions ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
        "last_sync_error": "ALTER TABLE subscriptions ADD COLUMN last_sync_error TEXT NOT NULL DEFAULT ''",
        "psa_cert_number": "ALTER TABLE subscriptions ADD COLUMN psa_cert_number TEXT NOT NULL DEFAULT ''",
        "jhs_card_id": "ALTER TABLE subscriptions ADD COLUMN jhs_card_id TEXT NOT NULL DEFAULT ''",
        "created_at": "ALTER TABLE subscriptions ADD COLUMN created_at TEXT NOT NULL DEFAULT ''",
        "updated_at": "ALTER TABLE subscriptions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)


def _ensure_snapshot_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(price_snapshots)").fetchall()
    }
    migrations = {
        "avg1_price": "ALTER TABLE price_snapshots ADD COLUMN avg1_price REAL",
        "avg7_price": "ALTER TABLE price_snapshots ADD COLUMN avg7_price REAL",
        "avg30_price": "ALTER TABLE price_snapshots ADD COLUMN avg30_price REAL",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)
