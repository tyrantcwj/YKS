from app import settings_store
from app.db import init_db


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr("app.config.settings.database_path", str(db_path))
    settings_store.invalidate()
    init_db()


def test_get_str_falls_back_to_env_default(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr("app.config.settings.psa_api_token", "")
    assert settings_store.get_str("psa_api_token") == ""
    # tcgdex_api_base default comes from settings.
    assert settings_store.get_str("tcgdex_api_base") == "https://api.tcgdex.net/v2"


def test_override_takes_precedence_and_clearing_reverts(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr("app.config.settings.psa_api_token", "env-default")

    settings_store.set_values({"psa_api_token": "from-ui"})
    assert settings_store.get_str("psa_api_token") == "from-ui"

    # Empty override means "use the env default".
    settings_store.set_values({"psa_api_token": ""})
    assert settings_store.get_str("psa_api_token") == "env-default"


def test_bool_override(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr("app.config.settings.jhs_enabled", False)
    assert settings_store.get_bool("jhs_enabled") is False

    settings_store.set_values({"jhs_enabled": "true"})
    assert settings_store.get_bool("jhs_enabled") is True

    settings_store.set_values({"jhs_enabled": "false"})
    assert settings_store.get_bool("jhs_enabled") is False


def test_unknown_keys_are_ignored(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    settings_store.set_values({"not_a_real_setting": "x"})
    assert settings_store.current_value("not_a_real_setting") == ""
    settings_store.invalidate()
