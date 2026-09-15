from __future__ import annotations

import uuid

import pytest


class Response:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}
        self.text = str(self._data)

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def notify_settings(settings):
    settings.NOTIFY_SERVER_URL = "http://notify.test"
    settings.NOTIFY_API_KEY = "secret"
    settings.NOTIFY_TIMEOUT = 5
    settings.NOTIFY_SYNC_TIMEOUT = 30


def test_sdk_send(monkeypatch):
    from notify.sdk import client

    seen = {}

    def request(method, path, **kwargs):
        seen.update(method=method, path=path, **kwargs)
        return Response(data={"external_id": "remote-id"})

    monkeypatch.setattr(client, "_request", request)
    assert client.post_send({"text": "oi"}, run_sync=True)["external_id"] == "remote-id"
    assert (seen["method"], seen["path"]) == ("POST", "/v1/send")


def test_send_async_enfileira_payload_estavel(monkeypatch):
    from django.db import transaction
    from django_q import tasks
    from notify.interface.send import send

    queued = []
    monkeypatch.setattr(transaction, "on_commit", lambda fn: fn())
    monkeypatch.setattr(tasks, "async_task", lambda *args: queued.append(args))
    result = send(
        text="oi",
        caller="test",
        phone="5511999999999",
        idempotency_key="business-key",
    )
    uuid.UUID(result)
    task, payload = queued[0]
    assert task == "notify.sdk.push.push_send"
    assert payload["external_id"] == "business-key"


@pytest.mark.django_db
def test_send_event_resolve_profile(monkeypatch):
    from django.db import transaction
    from django_q import tasks
    from notify.interface.events import send_event
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    profile = Profile.objects.create(
        user=user, name="Maria da Silva", phone="5511999999999", gender="F"
    )
    queued = []
    monkeypatch.setattr(transaction, "on_commit", lambda fn: fn())
    monkeypatch.setattr(tasks, "async_task", lambda *args: queued.append(args))

    send_event("lead.paid", profile=profile, ctx={"valor": "10"})

    task, payload = queued[0]
    assert task == "notify.sdk.push.push_send"
    assert "Maria" in payload["text"]
    assert payload["phone"] == "5511999999999"
    assert payload["whatsapp"] is True
    assert payload["caller"] == "event:lead.paid"


def test_send_event_404_retorna_none(monkeypatch):
    from notify.sdk import client

    monkeypatch.setattr(client, "_request", lambda *a, **k: Response(status=404))
    assert client.post_send_event({"event": "missing"}, run_sync=True) is None


def test_sdk_erro_explicito(monkeypatch):
    from notify.sdk import client

    monkeypatch.setattr(
        client, "_request", lambda *a, **k: Response(status=503, data={"detail": "down"})
    )
    with pytest.raises(client.NotifyServerError) as caught:
        client.post_send({"text": "oi"})
    assert caught.value.status_code == 503
