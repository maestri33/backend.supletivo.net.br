"""Testes unitários e de integração do Cloudflare Turnstile."""

from __future__ import annotations

import httpx
import pytest
from django.test import Client, override_settings
from ninja.testing import TestClient

from api.tools.router import api as tools_api
from integrations.turnstile import (
    CLOUDFLARE_TEST_ALWAYS_BLOCK_TOKEN,
    CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN,
    TurnstileClient,
    verify_turnstile,
)


@pytest.mark.django_db
def test_turnstile_test_always_pass_token():
    with override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA"):
        result = verify_turnstile(CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN)
        assert result.success is True
        assert result.error_codes == []


@pytest.mark.django_db
def test_turnstile_test_always_block_token():
    with override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="2x0000000000000000000000000000000AA"):
        result = verify_turnstile(CLOUDFLARE_TEST_ALWAYS_BLOCK_TOKEN)
        assert result.success is False
        assert "invalid-input-response" in result.error_codes


@pytest.mark.django_db
def test_turnstile_mock_remote_verification_success():
    def mock_post(self, url, *args, **kwargs):
        assert "siteverify" in url
        return httpx.Response(
            200,
            json={
                "success": True,
                "challenge_ts": "2026-08-27T12:00:00Z",
                "hostname": "supletivo.net.br",
                "action": "lead_registration",
            },
        )

    import unittest.mock as mock
    client = TurnstileClient(secret_key="secret-real-key", enabled=True)
    with mock.patch.object(httpx.Client, "post", mock_post):
        result = client.verify("custom_real_token_123", remote_ip="192.168.1.50")

    assert result.success is True
    assert result.hostname == "supletivo.net.br"
    assert result.action == "lead_registration"


@pytest.mark.django_db
def test_turnstile_mock_remote_verification_failure():
    def mock_post(self, url, *args, **kwargs):
        return httpx.Response(
            200,
            json={
                "success": False,
                "error-codes": ["timeout-or-duplicate"],
            },
        )

    import unittest.mock as mock
    client = TurnstileClient(secret_key="secret-real-key", enabled=True)
    with mock.patch.object(httpx.Client, "post", mock_post):
        result = client.verify("expired_token", remote_ip="192.168.1.50")

    assert result.success is False
    assert "timeout-or-duplicate" in result.error_codes


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_turnstile_async_verification():
    async def mock_post(self, url, *args, **kwargs):
        return httpx.Response(
            200,
            json={
                "success": True,
                "hostname": "maestri.group",
            },
        )

    import unittest.mock as mock
    client = TurnstileClient(secret_key="secret-real-key", enabled=True)
    with mock.patch.object(httpx.AsyncClient, "post", mock_post):
        result = await client.verify_async("valid_token_async")

    assert result.success is True
    assert result.hostname == "maestri.group"


@pytest.mark.django_db
def test_turnstile_bypass_when_disabled():
    with override_settings(TURNSTILE_ENABLED=False):
        result = verify_turnstile("any_random_token")
        assert result.success is True


@pytest.mark.django_db
def test_turnstile_tools_api_endpoint():
    client = TestClient(tools_api)
    with override_settings(TURNSTILE_ENABLED=True):
        resp = client.post(
            "/turnstile/verify",
            json={"token": CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN, "remote_ip": "127.0.0.1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
