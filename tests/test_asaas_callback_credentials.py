import json

import pytest

from core.system_config import clear_settings_cache, set_setting


@pytest.fixture(autouse=True)
def isolated_settings_cache():
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.mark.django_db
def test_event_token_rotation_preserves_separate_withdrawal_credential(client):
    event_token = "events-" + "a" * 48
    withdrawal_token = "withdrawals-" + "b" * 48
    set_setting("ASAAS_WEBHOOK_SECRET", event_token, is_secret=True)
    set_setting("ASAAS_TRANSFER_VALIDATION_SECRET", withdrawal_token, is_secret=True)
    payload = json.dumps({"type": "TRANSFER", "transfer": {"id": "unknown-operation"}})

    response = client.post(
        "/integrations/asaas/transfer-validation/",
        data=payload,
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN=withdrawal_token,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REFUSED"

    response = client.post(
        "/integrations/asaas/transfer-validation/",
        data=payload,
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN=event_token,
    )
    assert response.status_code == 401

    response = client.post(
        "/integrations/asaas/webhook/",
        data=json.dumps({"event": "PAYMENT_CREATED", "payment": {"id": "unmapped"}}),
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN=withdrawal_token,
    )
    assert response.status_code == 401

    response = client.post(
        "/integrations/asaas/webhook/",
        data=json.dumps({"event": "PAYMENT_CREATED", "payment": {"id": "unmapped"}}),
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN=event_token,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_legacy_shared_token_remains_supported_without_withdrawal_override(client, settings):
    settings.ASAAS_TRANSFER_VALIDATION_SECRET = ""
    token = "legacy-" + "c" * 48
    set_setting("ASAAS_WEBHOOK_SECRET", token, is_secret=True)
    response = client.post(
        "/integrations/asaas/transfer-validation/",
        data=json.dumps({"type": "TRANSFER", "transfer": {"id": "unknown-operation"}}),
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN=token,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REFUSED"


@pytest.mark.django_db
def test_withdrawal_callback_fails_closed_for_missing_or_wrong_token(client):
    set_setting("ASAAS_TRANSFER_VALIDATION_SECRET", "withdrawal-" + "d" * 48, is_secret=True)
    for header in ({}, {"HTTP_ASAAS_ACCESS_TOKEN": "wrong-token"}):
        response = client.post(
            "/integrations/asaas/transfer-validation/",
            data=json.dumps({"type": "TRANSFER", "transfer": {"id": "unknown-operation"}}),
            content_type="application/json",
            **header,
        )
        assert response.status_code == 401
