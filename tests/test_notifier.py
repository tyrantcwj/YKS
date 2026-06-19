import pytest

from app.config import settings
from app.notifier import AlertNotification, send_alert_notifications


class FakeResponse:
    def raise_for_status(self):
        return None


class FakeAsyncClient:
    posts = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json):
        self.posts.append({"url": url, "json": json, "timeout": self.timeout})
        return FakeResponse()


@pytest.mark.asyncio
async def test_send_alert_notifications_skips_when_webhook_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "alert_webhook_url", "")
    FakeAsyncClient.posts = []

    await send_alert_notifications(
        [
            AlertNotification(
                kind="target",
                message="Furret reached target price",
                card_id="swsh3-136",
                title="Furret",
            )
        ]
    )

    assert FakeAsyncClient.posts == []


@pytest.mark.asyncio
async def test_send_alert_notifications_posts_json(monkeypatch):
    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.test/hook")
    monkeypatch.setattr(settings, "alert_webhook_timeout_seconds", 3.0)
    monkeypatch.setattr("app.notifier.httpx.AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []

    await send_alert_notifications(
        [
            AlertNotification(
                kind="movement",
                message="Furret rose 10.0% to 1.10",
                card_id="swsh3-136",
                title="Furret",
            )
        ]
    )

    assert FakeAsyncClient.posts == [
        {
            "url": "https://example.test/hook",
            "timeout": 3.0,
            "json": {
                "source": "Pokemon Price Watch",
                "alerts": [
                    {
                        "kind": "movement",
                        "message": "Furret rose 10.0% to 1.10",
                        "card_id": "swsh3-136",
                        "title": "Furret",
                    }
                ],
            },
        }
    ]
