"""Testes para enforcement do Cloudflare Turnstile no funil de autenticação de clientes."""

import pytest
from django.test import override_settings

from integrations.turnstile.client import CLOUDFLARE_TEST_ALWAYS_BLOCK_TOKEN, CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN


@pytest.mark.django_db
def test_check_bypasses_turnstile_when_disabled(client):
    resp = client.post(
        "/api/v1/clients/auth/check",
        data={"cpf": "12345678901", "phone": "11999990000", "send_otp": False},
        content_type="application/json",
    )
    # Turnstile desativado por padrão => fluxo segue normalmente (200)
    assert resp.status_code == 200


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="test-secret")
def test_check_requires_turnstile_when_enabled(client):
    resp = client.post(
        "/api/v1/clients/auth/check",
        data={"cpf": "12345678901", "phone": "11999990000", "send_otp": False},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "Turnstile" in resp.json().get("detail", "")


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="test-secret")
def test_check_rejects_invalid_turnstile_token(client):
    resp = client.post(
        "/api/v1/clients/auth/check",
        data={
            "cpf": "12345678901",
            "phone": "11999990000",
            "send_otp": False,
            "turnstile_token": CLOUDFLARE_TEST_ALWAYS_BLOCK_TOKEN,
        },
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "Falha na verificação" in resp.json().get("detail", "")


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="test-secret")
def test_check_accepts_valid_turnstile_token(client):
    resp = client.post(
        "/api/v1/clients/auth/check",
        data={
            "cpf": "12345678901",
            "phone": "11999990000",
            "send_otp": False,
            "turnstile_token": CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN,
        },
        content_type="application/json",
    )
    assert resp.status_code == 200


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="test-secret")
def test_check_bypasses_turnstile_for_service_authenticated_bot(client, bot_headers):
    resp = client.post(
        "/api/v1/clients/auth/check",
        data={"cpf": "12345678901", "phone": "11999990000", "send_otp": False},
        content_type="application/json",
        **bot_headers,
    )
    assert resp.status_code == 200
