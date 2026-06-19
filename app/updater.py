import asyncio
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

APP_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = APP_ROOT / "app-version.json"
REPLACE_NAMES = [
    "app",
    "scripts",
    "tests",
    "pyproject.toml",
    "README.md",
    "README.zh-CN.md",
    ".env.example",
    "docker-compose.yml",
    "Dockerfile",
]


@dataclass(frozen=True)
class BuildInfo:
    version: str
    commit: str
    built_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_build_info() -> BuildInfo:
    if VERSION_FILE.exists():
        try:
            data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
            return BuildInfo(
                version=str(data.get("version") or "dev"),
                commit=str(data.get("commit") or "unknown"),
                built_at=str(data.get("builtAt") or data.get("built_at") or ""),
            )
        except (OSError, json.JSONDecodeError):
            pass
    return BuildInfo(
        version=os.getenv("APP_VERSION", "dev"),
        commit=os.getenv("APP_COMMIT", "unknown"),
        built_at=os.getenv("APP_BUILT_AT", ""),
    )


def write_build_info(version: str, commit: str) -> None:
    VERSION_FILE.write_text(
        json.dumps(
            {
                "version": version,
                "commit": commit,
                "builtAt": _now_iso(),
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )


def commits_differ(current: str, latest: str) -> bool:
    current = current.strip().lower()
    latest = latest.strip().lower()
    if not current or current == "unknown" or not latest:
        return False
    return not current.startswith(latest) and not latest.startswith(current)


def update_supported() -> bool:
    return settings.yks_update_mode.strip().lower() not in {"disabled", "off", "none"}


def _mirror_urls(url: str) -> list[str]:
    custom = settings.yks_github_mirror_prefix.strip()
    urls = []
    if custom:
        urls.append(f"{custom.rstrip('/')}/{url}")
    urls.append(url)
    return urls


async def _fetch_json(url: str) -> Any:
    errors: list[str] = []
    timeout = settings.yks_update_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "YKS"}) as client:
        for candidate in _mirror_urls(url):
            try:
                response = await client.get(candidate)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
    raise RuntimeError("; ".join(errors))


async def fetch_latest_commit() -> dict[str, str]:
    url = f"https://api.github.com/repos/{settings.yks_update_repo}/commits/{settings.yks_update_branch}"
    data = await _fetch_json(url)
    if not isinstance(data, dict) or not data.get("sha"):
        raise RuntimeError("GitHub commit response did not include a sha.")
    commit = data.get("commit") if isinstance(data.get("commit"), dict) else {}
    message = str(commit.get("message") or data["sha"]).splitlines()[0]
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    return {
        "commit": str(data["sha"]),
        "message": message,
        "date": str(committer.get("date") or ""),
    }


async def update_status() -> dict[str, Any]:
    current = read_build_info()
    runtime = {
        "mode": "source" if update_supported() else "disabled",
        "supported": update_supported(),
        "detail": (
            "Downloads the latest source archive, replaces app files in-place, installs dependencies, and restarts."
            if update_supported()
            else "Online source updates are disabled by YKS_UPDATE_MODE."
        ),
    }
    latest = None
    update_available = False
    if runtime["supported"]:
        latest = await fetch_latest_commit()
        update_available = commits_differ(current.commit, latest["commit"])
    return {
        "current": {
            "version": current.version,
            "commit": current.commit,
            "builtAt": current.built_at,
        },
        "latest": latest,
        "updateAvailable": update_available,
        "runtime": runtime,
        "updateRepo": settings.yks_update_repo,
        "updateBranch": settings.yks_update_branch,
    }


def _copytree_replace(source: Path, destination: Path) -> None:
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


async def _download_archive(destination: Path) -> None:
    url = (
        f"https://codeload.github.com/{settings.yks_update_repo}/tar.gz/"
        f"refs/heads/{settings.yks_update_branch}"
    )
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=settings.yks_update_timeout_seconds, headers={"User-Agent": "YKS"}) as client:
        for candidate in _mirror_urls(url):
            try:
                async with client.stream("GET", candidate) as response:
                    response.raise_for_status()
                    with destination.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
                return
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
    raise RuntimeError("; ".join(errors))


def _extract_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(destination, filter="data")
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if not roots:
        raise RuntimeError("Source archive did not contain a root directory.")
    return roots[0]


def _install_dependencies() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "."],
        cwd=APP_ROOT,
        check=True,
        timeout=600,
    )


def _schedule_restart() -> None:
    def exit_soon() -> None:
        os._exit(0)

    loop = asyncio.get_running_loop()
    loop.call_later(1.0, exit_soon)


async def apply_update() -> dict[str, Any]:
    if not update_supported():
        return {
            "ok": False,
            "mode": "disabled",
            "detail": "Online source updates are disabled.",
            "actions": [],
        }

    latest = await fetch_latest_commit()
    actions: list[str] = []
    with tempfile.TemporaryDirectory(prefix="yks-source-update-") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "source.tar.gz"
        extract_path = tmp_path / "extract"
        backup_path = APP_ROOT / f".update-backup-{int(datetime.now().timestamp())}"
        await _download_archive(archive_path)
        actions.append(f"Downloaded source {latest['commit'][:7]}")
        source_root = _extract_archive(archive_path, extract_path)
        actions.append("Extracted source archive")
        backup_path.mkdir(parents=True, exist_ok=True)
        backed_up: list[str] = []
        try:
            for name in REPLACE_NAMES:
                current = APP_ROOT / name
                incoming = source_root / name
                if not incoming.exists():
                    continue
                if current.exists():
                    _copytree_replace(current, backup_path / name)
                    backed_up.append(name)
                _copytree_replace(incoming, current)
            write_build_info("source", latest["commit"])
            _install_dependencies()
            actions.append("Installed Python dependencies")
        except Exception:
            for name in backed_up:
                _copytree_replace(backup_path / name, APP_ROOT / name)
            raise
    _schedule_restart()
    return {
        "ok": True,
        "mode": "source",
        "detail": f"Source updated to {latest['commit'][:7]}; service is restarting.",
        "actions": [*actions, "Scheduled process restart"],
    }
