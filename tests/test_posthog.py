"""Testes para o cliente de telemetria e eventos PostHog."""

import pytest
from django.test import override_settings

from integrations.posthog.client import (
    _scrub_properties,
    capture_event,
    is_posthog_enabled,
    track_funnel_checked,
    track_funnel_created,
    track_otp_event,
    track_payment_event,
)


def test_is_posthog_enabled_false_by_default():
    assert is_posthog_enabled() is False


@override_settings(POSTHOG_ENABLED=True, POSTHOG_API_KEY="phc_test_123")
def test_is_posthog_enabled_true_when_set():
    assert is_posthog_enabled() is True


def test_scrub_properties_removes_pii_keys():
    raw = {
        "cpf": "123.456.789-01",
        "phone": "5511999990000",
        "email": "user@example.com",
        "ref": "promoter-123",
        "payment_method": "pix",
        "notes": "Contato para CPF 123.456.789-01",
    }
    scrubbed = _scrub_properties(raw)

    # Chaves PII devem ser removidas
    assert "cpf" not in scrubbed
    assert "phone" not in scrubbed
    assert "email" not in scrubbed

    # Chaves de domínio permitidas são mantidas
    assert scrubbed["ref"] == "promoter-123"
    assert scrubbed["payment_method"] == "pix"

    # PII solta em texto livre é mascarada
    assert "123.456.789-01" not in scrubbed["notes"]
    assert "***01" in scrubbed["notes"]


@override_settings(POSTHOG_ENABLED=True, POSTHOG_API_KEY="phc_test_123")
def test_capture_event_sync_dispatches_payload(monkeypatch):
    recorded = {}

    class FakeResponse:
        status_code = 200
        text = '{"status": 1}'

    def fake_post(self, url, *args, **kwargs):
        recorded["url"] = url
        recorded["json"] = kwargs.get("json")
        return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx.Client, "post", fake_post)

    ok = capture_event("test_event", distinct_id="user_123", properties={"score": 10}, sync=True)
    assert ok is True
    assert recorded["url"] == "https://us.i.posthog.com/capture/"
    assert recorded["json"]["event"] == "test_event"
    assert recorded["json"]["distinct_id"] == "user_123"
    assert recorded["json"]["api_key"] == "phc_test_123"
    assert recorded["json"]["properties"]["score"] == 10
    assert recorded["json"]["properties"]["$lib"] == "backend.supletivo.net.br"


@override_settings(POSTHOG_ENABLED=True, POSTHOG_API_KEY="phc_test_123")
def test_track_helpers(monkeypatch):
    events = []

    monkeypatch.setattr(
        "integrations.posthog.client.capture_event",
        lambda event, distinct_id, properties=None, sync=False: events.append((event, distinct_id, properties)),
    )

    track_funnel_checked("lead_1", found=True, registered=False, ref="afiliado_x")
    track_funnel_created("lead_1", payment_method="card", ref="afiliado_x")
    track_otp_event("lead_1", action="verified")
    track_payment_event("lead_1", action="confirmed", amount="199.00", method="pix", provider="asaas")

    assert len(events) == 4
    assert events[0][0] == "funnel_lead_checked"
    assert events[0][2]["ref"] == "afiliado_x"
    assert events[1][0] == "funnel_lead_created"
    assert events[2][0] == "auth_otp_verified"
    assert events[3][0] == "payment_confirmed"
    assert events[3][2]["provider"] == "asaas"
