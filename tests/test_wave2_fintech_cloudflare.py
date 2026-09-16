"""Unit tests for Wave 2: FinTech & Cloudflare Synergy.
1. Asaas Pix QR storage with Cloudflare R2 integration.
2. Cloudflare Turnstile enforcement on POST /api/clients/lead/checkout.
"""

from __future__ import annotations

import base64
from unittest import mock
import pytest
from django.test import Client

from integrations.bank.asaas import qr as asaas_qr
from integrations.turnstile.client import TurnstileResult


def test_asaas_qr_save_pix_qr_png_without_r2(settings, tmp_path):
    """When R2 is not configured, qr saves to local filesystem and returns relative or local URL."""
    settings.R2_ENABLED = False
    settings.MEDIA_ROOT = str(tmp_path)
    settings.EXTERNAL_URL = "https://backend.supletivo.net.br"

    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    b64_png = base64.b64encode(dummy_png).decode("utf-8")

    url = asaas_qr.save_pix_qr_png("pay_123", b64_png)
    assert "pay_123.png" in url
    assert (tmp_path / "qrcodes" / "pay_123.png").exists()


def test_asaas_qr_save_pix_qr_png_with_r2(settings, tmp_path):
    """When R2 is configured, save_pix_qr_png uploads to R2 and returns CDN URL."""
    settings.R2_ENABLED = True
    settings.R2_ACCOUNT_ID = "fake_account"
    settings.R2_ACCESS_KEY_ID = "fake_key"
    settings.R2_SECRET_ACCESS_KEY = "fake_secret"
    settings.R2_BUCKET_NAME = "supletivo-media"
    settings.R2_PUBLIC_URL = "https://media.supletivo.net.br"
    settings.MEDIA_ROOT = str(tmp_path)

    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    b64_png = base64.b64encode(dummy_png).decode("utf-8")

    with mock.patch("integrations.bank.asaas.qr.upload_to_r2", return_value="https://media.supletivo.net.br/qrcodes/pay_999.png") as mock_upload:
        url = asaas_qr.save_pix_qr_png("pay_999", b64_png)
        assert url == "https://media.supletivo.net.br/qrcodes/pay_999.png"
        mock_upload.assert_called_once()


@pytest.mark.django_db
def test_lead_checkout_turnstile_enforcement(settings, client: Client):
    """POST /api/v1/clients/lead/checkout validates Turnstile token when enabled."""
    from users.auth.models import User
    from users.roles.lead.models import Lead
    from users.auth.jwt.service import issue

    # Create lead user and promoter user
    promoter = User.objects.create_user()
    user = User.objects.create_user()
    lead = Lead.objects.create(user=user, promoter=promoter, status="pending")
    tokens = issue(str(user.external_id), roles=["lead"])
    auth_header = f"Bearer {tokens['access_token']}"

    # 1. Turnstile disabled -> succeeds without token
    settings.TURNSTILE_ENABLED = False
    with mock.patch("users.roles.lead.service.set_checkout") as mock_set:
        mock_set.return_value = {
            "payment_method": "pix",
            "provider": "asaas",
            "amount": "5.00",
            "is_paid": False,
        }
        resp = client.post(
            "/api/v1/clients/lead/checkout",
            data={"payment_method": "pix"},
            content_type="application/json",
            HTTP_AUTHORIZATION=auth_header,
        )
        assert resp.status_code == 200

    # 2. Turnstile enabled -> 400 when token missing
    settings.TURNSTILE_ENABLED = True
    resp_missing = client.post(
        "/api/v1/clients/lead/checkout",
        data={"payment_method": "pix"},
        content_type="application/json",
        HTTP_AUTHORIZATION=auth_header,
    )
    assert resp_missing.status_code == 400
    assert "Turnstile" in resp_missing.json().get("detail", "")

    # 3. Turnstile enabled -> 400 when token verification fails
    with mock.patch("api.clients.routers.lead.verify_turnstile") as mock_verify:
        mock_verify.return_value = TurnstileResult(success=False, error_codes=["invalid-input-response"])
        resp_invalid = client.post(
            "/api/v1/clients/lead/checkout",
            data={"payment_method": "pix", "turnstile_token": "bad_token"},
            content_type="application/json",
            HTTP_AUTHORIZATION=auth_header,
        )
        assert resp_invalid.status_code == 400
        assert "Turnstile" in resp_invalid.json().get("detail", "")

    # 4. Turnstile enabled -> 200 when token verification succeeds
    with mock.patch("api.clients.routers.lead.verify_turnstile") as mock_verify, \
         mock.patch("users.roles.lead.service.set_checkout") as mock_set:
        mock_verify.return_value = TurnstileResult(success=True)
        mock_set.return_value = {
            "payment_method": "pix",
            "provider": "asaas",
            "amount": "5.00",
            "is_paid": False,
        }
        resp_valid = client.post(
            "/api/v1/clients/lead/checkout",
            data={"payment_method": "pix", "turnstile_token": "valid_token"},
            content_type="application/json",
            HTTP_AUTHORIZATION=auth_header,
        )
        assert resp_valid.status_code == 200
