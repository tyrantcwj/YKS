"""Database access layer with optional MySQL backend.

By default the app uses a local SQLite file (``data/app.db``). You can instead
point it at your own MySQL server (8.0.13+, needed for window functions / CTEs
and ``DEFAULT (expr)`` on text columns) by setting a connection URL:

    mysql://user:password@host:3306/dbname

The URL is resolved from (in priority order):

1. ``data/instance.json`` -> ``{"database_url": "..."}`` (written by the
   /settings page so it can be changed from the UI without editing env/compose)
2. the ``DATABASE_URL`` env / config value

It deliberately does *not* live in the DB-backed settings store, because that
store reads from the very database we're trying to connect to.

Repository SQL is written once with ``?`` placeholders and SQLite-flavoured
syntax; :class:`_Conn` translates placeholders (and drops ``COLLATE NOCASE``)
for MySQL so the rest of the app stays dialect-agnostic.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.config import settings

_INSTANCE_FILE = Path("data/instance.json")

# Tiny cache so we don't stat/parse the sidecar on every connection. Invalidated
# whenever the URL is changed via :func:`set_database_url`.
_url_cache: dict[str, Any] = {"loaded": False, "url": ""}


def _read_sidecar_url() -> str:
    try:
        data = json.loads(_INSTANCE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("database_url") or "").strip()


def effective_database_url() -> str:
    if not _url_cache["loaded"]:
        url = _read_sidecar_url() or (settings.database_url or "").strip()
        _url_cache["url"] = url
        _url_cache["loaded"] = True
    return _url_cache["url"]


def invalidate_url_cache() -> None:
    _url_cache["loaded"] = False
    _url_cache["url"] = ""


def dialect() -> str:
    url = effective_database_url()
    if url.startswith(("mysql://", "mysql+pymysql://")):
        return "mysql"
    return "sqlite"


class _Conn:
    """Thin wrapper exposing a uniform ``execute``/``commit``/``close`` API.

    ``execute`` returns a DB-API cursor whose ``fetchone``/``fetchall`` yield
    mapping-style rows (``sqlite3.Row`` for SQLite, ``dict`` via PyMySQL's
    ``DictCursor`` for MySQL) so callers can use ``row["col"]`` / ``row.keys()``
    / ``dict(row)`` either way.
    """

    def __init__(self, raw: Any, dialect_name: str) -> None:
        self._raw = raw
        self.dialect = dialect_name

    def execute(self, sql: str, params: tuple | list = ()):  # noqa: ANN201
        if self.dialect == "mysql":
            translated = sql.replace("?", "%s").replace("COLLATE NOCASE", "")
            cursor = self._raw.cursor()
            cursor.execute(translated, tuple(params))
            return cursor
        return self._raw.execute(sql, params)

    def executescript(self, script: str) -> None:
        self._raw.executescript(script)

    def commit(self) -> None:
        self._raw.commit()

    def close(self) -> None:
        self._raw.close()


def _connect_mysql() -> _Conn:
    import pymysql
    from pymysql.cursors import DictCursor

    url = effective_database_url().replace("mysql+pymysql://", "mysql://")
    parsed = urlparse(url)
    raw = pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=(parsed.path or "").lstrip("/") or None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
    )
    return _Conn(raw, "mysql")


def _connect_sqlite() -> _Conn:
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return _Conn(conn, "sqlite")


def _connect() -> _Conn:
    if dialect() == "mysql":
        return _connect_mysql()
    return _connect_sqlite()


@contextmanager
def get_db() -> Iterator[_Conn]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def check_connection(url: str) -> None:
    """Open a throwaway connection to ``url`` (raises on failure).

    Used by the settings page to validate a MySQL URL before switching to it.
    An empty URL means "use SQLite", which always works.
    """

    url = (url or "").strip()
    if not url:
        return
    if not url.startswith(("mysql://", "mysql+pymysql://")):
        raise ValueError("数据库地址需以 mysql:// 开头，例如 mysql://user:pass@host:3306/dbname")
    import pymysql

    parsed = urlparse(url.replace("mysql+pymysql://", "mysql://"))
    if not (parsed.path or "").lstrip("/"):
        raise ValueError("缺少数据库名，例如 mysql://user:pass@host:3306/yks")
    conn = pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=(parsed.path or "").lstrip("/"),
        charset="utf8mb4",
        connect_timeout=10,
    )
    conn.close()


def set_database_url(url: str) -> None:
    """Persist the DB URL to the sidecar and apply it immediately.

    Validates first, then writes ``data/instance.json`` and runs schema init so
    the change takes effect without restarting the container. On failure the
    previous URL is left untouched.
    """

    url = (url or "").strip()
    check_connection(url)
    _INSTANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    previous = _read_sidecar_url()
    _INSTANCE_FILE.write_text(
        json.dumps({"database_url": url}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    invalidate_url_cache()
    try:
        init_db()
    except Exception:
        # Roll back to the previous sidecar value so the app keeps working.
        _INSTANCE_FILE.write_text(
            json.dumps({"database_url": previous}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        invalidate_url_cache()
        raise


_SQLITE_DDL = """
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

# MySQL 8.0.13+ DDL. TEXT columns that need a default use DEFAULT (expr); short
# identifier-ish columns become VARCHAR so they can carry plain defaults / be
# indexed (card_id is UNIQUE / PRIMARY KEY).
_MYSQL_DDL = [
    """
    CREATE TABLE IF NOT EXISTS subscriptions (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        card_id VARCHAR(191) NOT NULL UNIQUE,
        nickname VARCHAR(255) NOT NULL DEFAULT '',
        variant VARCHAR(64) NOT NULL DEFAULT 'holo',
        tcgdex_locale VARCHAR(16) NOT NULL DEFAULT '',
        target_price DOUBLE NULL,
        alert_percent DOUBLE NULL,
        active TINYINT NOT NULL DEFAULT 1,
        last_sync_error VARCHAR(500) NOT NULL DEFAULT '',
        psa_cert_number VARCHAR(64) NOT NULL DEFAULT '',
        jhs_card_id VARCHAR(64) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cards (
        card_id VARCHAR(191) PRIMARY KEY,
        name VARCHAR(512) NOT NULL,
        image_url VARCHAR(1024) NULL,
        set_name VARCHAR(512) NULL,
        rarity VARCHAR(128) NULL,
        last_synced_at DATETIME NULL,
        raw_json LONGTEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        subscription_id BIGINT NOT NULL,
        card_id VARCHAR(191) NOT NULL,
        provider VARCHAR(64) NOT NULL,
        currency VARCHAR(16) NOT NULL,
        variant VARCHAR(64) NOT NULL,
        market_price DOUBLE NULL,
        low_price DOUBLE NULL,
        mid_price DOUBLE NULL,
        high_price DOUBLE NULL,
        direct_price DOUBLE NULL,
        trend_price DOUBLE NULL,
        avg1_price DOUBLE NULL,
        avg7_price DOUBLE NULL,
        avg30_price DOUBLE NULL,
        snapshot_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_snapshots_card_time (card_id, snapshot_at),
        INDEX idx_snapshots_subscription_time (subscription_id, snapshot_at),
        CONSTRAINT fk_snapshot_sub FOREIGN KEY (subscription_id)
            REFERENCES subscriptions(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        subscription_id BIGINT NOT NULL,
        kind VARCHAR(64) NOT NULL,
        message VARCHAR(1024) NOT NULL,
        seen TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_alert_sub FOREIGN KEY (subscription_id)
            REFERENCES subscriptions(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        `key` VARCHAR(191) PRIMARY KEY,
        value LONGTEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS psa_certs (
        subscription_id BIGINT PRIMARY KEY,
        cert_number VARCHAR(64) NOT NULL,
        grade VARCHAR(64) NULL,
        subject VARCHAR(512) NULL,
        year VARCHAR(32) NULL,
        brand VARCHAR(255) NULL,
        card_number VARCHAR(64) NULL,
        variety VARCHAR(255) NULL,
        spec_id VARCHAR(64) NULL,
        population_total INT NULL,
        population_higher INT NULL,
        fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        raw_json LONGTEXT NOT NULL,
        CONSTRAINT fk_psa_sub FOREIGN KEY (subscription_id)
            REFERENCES subscriptions(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def init_db() -> None:
    with get_db() as db:
        if db.dialect == "mysql":
            for statement in _MYSQL_DDL:
                db.execute(statement)
        else:
            db.executescript(_SQLITE_DDL)
            _ensure_subscription_columns(db)
            _ensure_snapshot_columns(db)


def backup_database(destination: Path) -> None:
    if dialect() == "mysql":
        raise RuntimeError("MySQL 模式不支持 SQLite 文件备份，请用 mysqldump 备份你的 MySQL 数据库。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(settings.database_path)
    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _ensure_subscription_columns(db: _Conn) -> None:
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(subscriptions)").fetchall()
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
            db.execute(statement)


def _ensure_snapshot_columns(db: _Conn) -> None:
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(price_snapshots)").fetchall()
    }
    migrations = {
        "avg1_price": "ALTER TABLE price_snapshots ADD COLUMN avg1_price REAL",
        "avg7_price": "ALTER TABLE price_snapshots ADD COLUMN avg7_price REAL",
        "avg30_price": "ALTER TABLE price_snapshots ADD COLUMN avg30_price REAL",
    }
    for column, statement in migrations.items():
        if column not in columns:
            db.execute(statement)
