"""Runtime-editable settings stored in the database.

Values configured here (via the /settings page) override the environment /
``.env`` defaults from :mod:`app.config`, so tokens and toggles can be changed
from the web UI without editing compose or restarting the container. An empty
stored value means "fall back to the env default".

A tiny in-process cache avoids a DB read on every lookup; it is invalidated
whenever values are saved.
"""

import logging
import sqlite3

from app.config import settings
from app.db import get_db

logger = logging.getLogger(__name__)

# key -> (label, kind, placeholder). ``kind`` is one of text/password/bool.
EDITABLE_SETTINGS: dict[str, tuple[str, str, str]] = {
    "tcgdex_api_base": (
        "TCGdex API 地址",
        "text",
        "https://api.tcgdex.net/v2（被墙时填可用反代，保留 /v2 结尾）",
    ),
    "pokemontcg_api_key": (
        "pokemontcg.io API Key",
        "password",
        "缺图回退取图用，可留空（填了更稳定）",
    ),
    "psa_api_token": (
        "PSA API Token",
        "password",
        "psacard.com/publicapi 生成，用于查评级/族群",
    ),
    "jhs_enabled": (
        "启用集换社抓取（实验性）",
        "bool",
        "",
    ),
    "jhs_api_base": (
        "集换社抓取地址（实验性）",
        "text",
        "能返回价格 JSON 的中转地址，留空则不抓",
    ),
    "pikaqian_api_key": (
        "PikaQian API Key（简中卡库/价格）",
        "password",
        "pikaqian.com 注册生成 pk_live_…，填了搜索才会带 PikaQian 简中卡",
    ),
    "chs_image_base": (
        "国行卡图地址前缀",
        "text",
        "默认走 jsDelivr，被墙时可换成你的 GitHub 镜像（以 / 结尾）",
    ),
    "alert_webhook_url": (
        "提醒 Webhook 地址",
        "text",
        "ntfy / Bark / 企业微信机器人等，留空不推送",
    ),
}

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            with get_db() as db:
                rows = db.execute("SELECT key, value FROM app_settings").fetchall()
            _cache = {row["key"]: row["value"] for row in rows}
        except sqlite3.Error:
            logger.debug("app_settings not readable yet", exc_info=True)
            _cache = {}
    return _cache


def invalidate() -> None:
    global _cache
    _cache = None


def _default(key: str) -> str:
    value = getattr(settings, key, "")
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def get_str(key: str) -> str:
    override = _load().get(key, "")
    if override.strip():
        return override
    return _default(key)


def get_bool(key: str) -> bool:
    override = _load().get(key, "")
    if override.strip():
        return override.strip().lower() in ("1", "true", "yes", "on")
    return str(_default(key)).strip().lower() in ("1", "true", "yes", "on")


def current_value(key: str) -> str:
    """Value to prefill the form with: the stored override, else the default."""

    overrides = _load()
    if key in overrides:
        return overrides[key]
    return _default(key)


def set_values(values: dict[str, str]) -> None:
    with get_db() as db:
        for key, value in values.items():
            if key not in EDITABLE_SETTINGS:
                continue
            db.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
    invalidate()
