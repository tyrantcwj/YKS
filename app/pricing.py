import asyncio
import logging
import sqlite3

from app import repository
from app.db import get_db
from app.jihuanshe import fetch_prices as fetch_jhs_prices
from app.notifier import AlertNotification, send_alert_notifications
from app.psa import fetch_cert as fetch_psa_cert
from app.tcgdex import CardNotFoundError, fetch_card

logger = logging.getLogger(__name__)


def display_price(row: sqlite3.Row | None) -> float | None:
    if row is None:
        return None
    for key in ("market_price", "trend_price", "mid_price", "low_price"):
        value = row[key]
        if value is not None:
            return float(value)
    return None


def _alert_for_thresholds(
    db: sqlite3.Connection,
    subscription: sqlite3.Row,
    latest: sqlite3.Row | None,
    previous: sqlite3.Row | None,
) -> list[AlertNotification]:
    notifications: list[AlertNotification] = []
    latest_value = display_price(latest)
    if latest_value is None:
        return notifications

    card_title = subscription["nickname"] or subscription["card_id"]
    previous_value = display_price(previous)
    target_price = subscription["target_price"]
    if (
        target_price is not None
        and latest_value <= float(target_price)
        and (previous_value is None or previous_value > float(target_price))
    ):
        message = f"{card_title} 达到目标价：{latest_value:.2f} <= {float(target_price):.2f}"
        repository.create_alert(db, subscription["id"], "target", message)
        notifications.append(
            AlertNotification(
                kind="target",
                message=message,
                card_id=subscription["card_id"],
                title=card_title,
            )
        )

    alert_percent = subscription["alert_percent"]
    if alert_percent is None or previous_value in (None, 0):
        return notifications

    change = ((latest_value - previous_value) / previous_value) * 100
    if abs(change) >= float(alert_percent):
        direction = "上涨" if change > 0 else "下跌"
        message = f"{card_title} {direction} {abs(change):.1f}%，当前 {latest_value:.2f}"
        repository.create_alert(db, subscription["id"], "movement", message)
        notifications.append(
            AlertNotification(
                kind="movement",
                message=message,
                card_id=subscription["card_id"],
                title=card_title,
            )
        )
    return notifications


async def sync_subscription(subscription_id: int) -> bool:
    """Sync one subscription. Returns True on success.

    Network/API failures are recorded on the subscription instead of raising,
    so the web request that triggered the sync still completes cleanly.
    """
    with get_db() as db:
        subscription = repository.get_subscription(db, subscription_id)
        if subscription is None:
            return False
        keys = subscription.keys()
        card_id = subscription["card_id"]
        locale = subscription["tcgdex_locale"] or None
        psa_cert_number = subscription["psa_cert_number"] if "psa_cert_number" in keys else ""
        jhs_card_id = subscription["jhs_card_id"] if "jhs_card_id" in keys else ""

    try:
        payload = await fetch_card(card_id, locale)
    except CardNotFoundError:
        message = f"TCGdex 找不到卡片 {card_id}，请确认卡片 ID 是否正确。"
        logger.warning("Card %s was not found", card_id)
        with get_db() as db:
            repository.set_sync_error(db, subscription_id, message)
        return False
    except Exception as exc:  # noqa: BLE001 - surface any sync failure to the UI
        message = f"同步失败：{exc.__class__.__name__}: {exc}"
        logger.exception("Failed to sync card %s", card_id)
        with get_db() as db:
            repository.set_sync_error(db, subscription_id, message)
        return False

    # Optional, fail-soft extra sources. Network calls happen outside the DB
    # context so a slow/blocked provider never holds a write transaction open.
    psa_cert = None
    if (psa_cert_number or "").strip():
        psa_cert = await fetch_psa_cert(psa_cert_number)
    jhs_prices = await fetch_jhs_prices(jhs_card_id) if (jhs_card_id or "").strip() else []

    notifications: list[AlertNotification] = []
    with get_db() as db:
        subscription = repository.get_subscription(db, subscription_id)
        if subscription is None:
            return False
        repository.save_card_payload(db, subscription_id, payload)
        for price in jhs_prices:
            repository.save_price_snapshot(db, subscription_id, card_id, price)
        if psa_cert is not None:
            repository.save_psa_cert(db, subscription_id, psa_cert)
        repository.set_sync_error(db, subscription_id, "")
        latest = repository.latest_price_for_variant(
            db,
            subscription_id,
            subscription["variant"],
        )
        previous = repository.previous_price_for_variant(
            db,
            subscription_id,
            subscription["variant"],
        )
        notifications = _alert_for_thresholds(db, subscription, latest, previous)

    await send_alert_notifications(notifications)
    return True


async def sync_all_subscriptions() -> None:
    with get_db() as db:
        subscriptions = repository.active_subscriptions(db)

    for subscription in subscriptions:
        try:
            await sync_subscription(subscription["id"])
        except Exception:
            logger.exception("Failed to sync card %s", subscription["card_id"])


def run_sync_all_blocking() -> None:
    asyncio.run(sync_all_subscriptions())
