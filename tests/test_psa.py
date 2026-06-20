import sqlite3

from app import repository
from app.db import init_db
from app.psa import parse_cert


SAMPLE_BODY = {
    "IsValidRequest": True,
    "ServerMessage": "Request successful",
    "PSACert": {
        "CertNumber": "12345678",
        "SpecID": "12168745",
        "CardGrade": "10",
        "Subject": "Charizard",
        "Year": "1999",
        "Brand": "Pokemon Game",
        "CardNumber": "4",
        "Variety": "Holo",
        "TotalPopulation": 8849,
        "PopulationHigher": 0,
    },
}


def test_parse_cert_extracts_fields():
    cert = parse_cert("12345678", SAMPLE_BODY)
    assert cert is not None
    assert cert.grade == "10"
    assert cert.subject == "Charizard"
    assert cert.year == "1999"
    assert cert.population_total == 8849
    assert cert.population_higher == 0
    assert cert.spec_id == "12168745"


def test_parse_cert_rejects_invalid_request():
    assert parse_cert("0", {"IsValidRequest": False, "ServerMessage": "Invalid CertNo"}) is None
    assert parse_cert("0", {"IsValidRequest": True}) is None
    assert parse_cert("0", "not a dict") is None


def test_save_and_get_psa_cert(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        subscription_id = repository.create_subscription(
            conn,
            card_id="base1-4",
            nickname="Charizard",
            variant="holo",
            target_price=None,
            alert_percent=None,
        )
        cert = parse_cert("12345678", SAMPLE_BODY)
        repository.save_psa_cert(conn, subscription_id, cert)
        conn.commit()

        stored = repository.get_psa_cert(conn, subscription_id)
        assert stored["grade"] == "10"
        assert stored["population_total"] == 8849
        assert stored["subject"] == "Charizard"

        # Saving again upserts (no duplicate row, values refreshed).
        repository.save_psa_cert(conn, subscription_id, cert)
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM psa_certs WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()["n"]
        assert count == 1

        # The dashboard join surfaces the grade as a badge.
        rows = repository.list_subscriptions(conn)
        assert rows[0]["psa_grade"] == "10"

        repository.delete_psa_cert(conn, subscription_id)
        conn.commit()
        assert repository.get_psa_cert(conn, subscription_id) is None
    finally:
        conn.close()
