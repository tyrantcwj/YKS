import json

import pytest

from app import db


@pytest.fixture(autouse=True)
def _isolate_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_INSTANCE_FILE", tmp_path / "instance.json")
    db.invalidate_url_cache()
    yield
    db.invalidate_url_cache()


def test_default_dialect_is_sqlite():
    assert db.dialect() == "sqlite"


def test_sidecar_overrides_and_detects_mysql(monkeypatch):
    db._INSTANCE_FILE.write_text(
        json.dumps({"database_url": "mysql://u:p@h:3306/yks"}), encoding="utf-8"
    )
    db.invalidate_url_cache()
    assert db.dialect() == "mysql"
    assert db.effective_database_url() == "mysql://u:p@h:3306/yks"


class _FakeCursor:
    def __init__(self):
        self.executed = None

    def execute(self, sql, params):
        self.executed = (sql, params)


class _FakeRaw:
    def __init__(self):
        self.cursor_obj = _FakeCursor()

    def cursor(self):
        return self.cursor_obj


def test_mysql_execute_translates_placeholders_and_collation():
    raw = _FakeRaw()
    conn = db._Conn(raw, "mysql")
    conn.execute("SELECT * FROM t WHERE a = ? ORDER BY title COLLATE NOCASE ASC", ("x",))
    sql, params = raw.cursor_obj.executed
    assert "?" not in sql
    assert "%s" in sql
    assert "COLLATE NOCASE" not in sql
    assert params == ("x",)


def test_check_connection_empty_is_sqlite_noop():
    db.check_connection("")  # no raise


def test_check_connection_rejects_non_mysql_scheme():
    with pytest.raises(ValueError):
        db.check_connection("postgres://u:p@h/db")


def test_check_connection_requires_database_name():
    with pytest.raises(ValueError):
        db.check_connection("mysql://u:p@h:3306/")


def test_set_database_url_empty_keeps_sqlite():
    db.set_database_url("")
    assert db.dialect() == "sqlite"
    assert json.loads(db._INSTANCE_FILE.read_text(encoding="utf-8"))["database_url"] == ""


def test_build_mysql_url_encodes_special_chars():
    url = db.build_mysql_url("10.0.0.5", "3306", "root", "p@ss:w/rd.", "yks")
    assert url == "mysql://root:p%40ss%3Aw%2Frd.@10.0.0.5:3306/yks"
    # And it must round-trip back through urlparse without the cast error.
    parts = db.parse_mysql_url(url)
    assert parts["host"] == "10.0.0.5"
    assert parts["port"] == "3306"
    assert parts["user"] == "root"
    assert parts["password"] == "p@ss:w/rd."
    assert parts["name"] == "yks"


def test_build_mysql_url_empty_host_means_sqlite():
    assert db.build_mysql_url("", "3306", "root", "x", "yks") == ""


def test_build_mysql_url_rejects_bad_port():
    with pytest.raises(ValueError):
        db.build_mysql_url("h", "Tyrantcwj1996.", "root", "x", "yks")


def test_build_mysql_url_requires_name():
    with pytest.raises(ValueError):
        db.build_mysql_url("h", "3306", "root", "x", "")
