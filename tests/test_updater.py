import json

import pytest

from app import updater


def test_commits_differ_handles_prefixes_and_unknown():
    assert not updater.commits_differ("unknown", "abcdef")
    assert not updater.commits_differ("abcdef", "abcdef123")
    assert updater.commits_differ("abcdef", "123456")


def test_read_build_info_from_file(tmp_path, monkeypatch):
    version_file = tmp_path / "app-version.json"
    version_file.write_text(
        json.dumps({"version": "source", "commit": "abc123", "builtAt": "2026-06-19T00:00:00Z"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater, "VERSION_FILE", version_file)

    info = updater.read_build_info()

    assert info.version == "source"
    assert info.commit == "abc123"
    assert info.built_at == "2026-06-19T00:00:00Z"


@pytest.mark.asyncio
async def test_update_status_reports_latest_commit(monkeypatch):
    monkeypatch.setattr(updater, "read_build_info", lambda: updater.BuildInfo("source", "abc123", ""))

    async def fake_latest():
        return {"commit": "def456", "message": "new", "date": "2026-06-19T00:00:00Z"}

    monkeypatch.setattr(updater, "fetch_latest_commit", fake_latest)

    status = await updater.update_status()

    assert status["current"]["commit"] == "abc123"
    assert status["latest"]["commit"] == "def456"
    assert status["updateAvailable"] is True
    assert status["runtime"]["mode"] == "source"
