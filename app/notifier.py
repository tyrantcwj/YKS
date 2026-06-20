import logging
from dataclasses import dataclass

import httpx

from app import settings_store
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertNotification:
    kind: str
    message: str
    card_id: str
    title: str


async def send_alert_notifications(notifications: list[AlertNotification]) -> None:
    webhook_url = settings_store.get_str("alert_webhook_url").strip()
    if not webhook_url or not notifications:
        return

    payload = {
        "source": settings.app_name,
        "alerts": [
            {
                "kind": notification.kind,
                "message": notification.message,
                "card_id": notification.card_id,
                "title": notification.title,
            }
            for notification in notifications
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=settings.alert_webhook_timeout_seconds) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("Failed to send alert webhook notification")
