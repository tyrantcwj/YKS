from fastapi.testclient import TestClient
import sqlite3

from app import main
from app import repository
from app.db import init_db
from app.models import CardSearchResult, PricePoint


def test_dashboard_renders_search_results(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    init_db()

    async def fake_search_cards(query):
        assert query == "pikachu"
        return [
            CardSearchResult(
                card_id="basep-1",
                name="Pikachu",
                image_url="https://assets.tcgdex.net/en/base/basep/1/low.webp",
                tcgdex_locale="en",
                local_id="1",
            )
        ]

    monkeypatch.setattr(main, "search_cards", fake_search_cards)

    with TestClient(main.app) as client:
        response = client.get("/?q=pikachu")

    assert response.status_code == 200
    assert "Pikachu" in response.text
    assert "basep-1" in response.text


def test_export_routes_return_csv(tmp_path, monkeypatch):
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
            target_price=1.0,
            alert_percent=10.0,
        )
        repository.save_price_snapshot(
            conn,
            subscription_id,
            "basep-1",
            PricePoint(
                provider="tcgplayer",
                currency="USD",
                variant="normal",
                market_price=0.5,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    with TestClient(main.app) as client:
        subscriptions = client.get("/export/subscriptions.csv")
        prices = client.get("/export/prices.csv")

    assert subscriptions.status_code == 200
    assert "text/csv" in subscriptions.headers["content-type"]
    assert 'filename="subscriptions.csv"' in subscriptions.headers["content-disposition"]
    assert "basep-1" in subscriptions.text
    assert "Pikachu" in subscriptions.text

    assert prices.status_code == 200
    assert "text/csv" in prices.headers["content-type"]
    assert 'filename="price-snapshots.csv"' in prices.headers["content-disposition"]
    assert "tcgplayer" in prices.text
    assert "0.5" in prices.text


def test_database_backup_route_returns_readable_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        repository.create_subscription(
            conn,
            card_id="basep-1",
            nickname="Pikachu",
            variant="normal",
            target_price=None,
            alert_percent=None,
        )
        conn.commit()
    finally:
        conn.close()

    with TestClient(main.app) as client:
        response = client.get("/export/database.sqlite")

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('filename="pokemon-price-watch.sqlite"')

    backup_path = tmp_path / "backup.sqlite"
    backup_path.write_bytes(response.content)

    backup = sqlite3.connect(backup_path)
    try:
        count = backup.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    finally:
        backup.close()

    assert count == 1


def test_subscription_detail_renders_price_chart(tmp_path, monkeypatch):
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
            PricePoint(provider="tcgplayer", currency="USD", variant="normal", market_price=2.0),
        )
        conn.commit()
    finally:
        conn.close()

    with TestClient(main.app) as client:
        response = client.get(f"/subscriptions/{subscription_id}")

    assert response.status_code == 200
    assert "价格走势" in response.text
    assert "<polyline" in response.text
    assert "2 条记录" in response.text


def test_update_page_renders_status(monkeypatch):
    async def fake_update_status():
        return {
            "current": {"version": "source", "commit": "abc123", "builtAt": ""},
            "latest": {"commit": "def456", "message": "new", "date": ""},
            "updateAvailable": True,
            "runtime": {"mode": "source", "supported": True, "detail": "Downloads source."},
            "updateRepo": "tyrantcwj/YKS",
            "updateBranch": "main",
        }

    monkeypatch.setattr(main, "update_status", fake_update_status)

    with TestClient(main.app) as client:
        response = client.get("/update")

    assert response.status_code == 200
    assert "在线更新" in response.text
    assert "发现新版本" in response.text
    assert "立即更新" in response.text
