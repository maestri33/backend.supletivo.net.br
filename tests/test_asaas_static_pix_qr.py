"""Testes para o fluxo de emissão de QR Code PIX Estático Direto (Asaas).

Cobre:
- create_pix_qr: emissão com sucesso, idempotência e erros.
- webhooks: reconciliação PAYMENT_RECEIVED de static_pix_qr.
- _fill_pix: lead/service.py agora usa static_qr (não create_charge).
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import override_settings

from integrations.bank.asaas import static_qr as asaas_static_qr
from integrations.bank.asaas.models import Payment
from integrations.bank.asaas import webhooks as asaas_webhooks
from integrations.bank.asaas.client import AsaasClient, AsaasError


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

TEST_PIX_KEY = "d790e14b-b627-4f07-8f8b-6aef38a07ed6"
TEST_QR_ID = "V7MEMPRE00000696576289ASA"
TEST_QR_PAYLOAD = "00020126770014br.gov.bcb.pix0136d790e14b-b627-4f07-8f8b-6aef38a07ed60000..."
TEST_QR_IMAGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _mock_pix_keys_resp():
    return {
        "totalCount": 1,
        "data": [{"id": "key-id-001", "key": TEST_PIX_KEY, "type": "EVP", "status": "ACTIVE"}],
    }


def _mock_static_qr_resp(ext_ref: str):
    return {
        "id": TEST_QR_ID,
        "payload": TEST_QR_PAYLOAD,
        "encodedImage": TEST_QR_IMAGE,
        "externalReference": ext_ref,
        "allowsMultiplePayments": False,
    }


# ──────────────────────────────────────────────────────────────
# Testes de create_pix_qr
# ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_create_pix_qr_success(monkeypatch):
    """create_pix_qr cria Payment(kind=STATIC_PIX_QR) com payload e imagen corretos."""
    pid = f"sqr_test_{uuid.uuid4().hex[:8]}"
    resp = _mock_static_qr_resp(pid)

    async def mock_list_keys(self, params=None):
        return _mock_pix_keys_resp()

    async def mock_create_qr(self, payload):
        assert payload["addressKey"] == TEST_PIX_KEY
        assert payload["value"] == 5.00
        assert payload["allowsMultiplePayments"] is False
        assert payload["externalReference"] == pid
        return resp

    monkeypatch.setattr(AsaasClient, "list_pix_address_keys", mock_list_keys)
    monkeypatch.setattr(AsaasClient, "create_static_qr_code", mock_create_qr)

    with patch("integrations.bank.asaas.static_qr.save_pix_qr_png", return_value=None):
        payment = asaas_static_qr.create_pix_qr(
            amount=Decimal("5.00"),
            description="Matrícula Supletivo",
            payment_id=pid,
        )

    assert payment.kind == Payment.Kind.STATIC_PIX_QR
    assert payment.billing_type == "PIX"
    assert payment.status == "PENDING"
    assert payment.qrcode_payload == TEST_QR_PAYLOAD
    assert payment.asaas_id == TEST_QR_ID
    assert payment.amount == Decimal("5.00")
    assert payment.customer_id is None  # QR estático NÃO cria customer


@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_create_pix_qr_invalid_amount():
    """create_pix_qr rejeita valores inválidos."""
    with pytest.raises(asaas_static_qr.StaticQrError, match="amount_required"):
        asaas_static_qr.create_pix_qr(amount=None, payment_id="test_none")
    with pytest.raises(asaas_static_qr.StaticQrError, match="amount_must_be_positive"):
        asaas_static_qr.create_pix_qr(amount="-10.00", payment_id="test_neg")


@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_create_pix_qr_idempotent(monkeypatch):
    """Segundo create com mesmo payment_id falha em idempotência (não duplica)."""
    pid = f"sqr_idem_{uuid.uuid4().hex[:8]}"

    async def mock_list_keys(self, params=None):
        return _mock_pix_keys_resp()

    async def mock_create_qr(self, payload):
        return _mock_static_qr_resp(pid)

    monkeypatch.setattr(AsaasClient, "list_pix_address_keys", mock_list_keys)
    monkeypatch.setattr(AsaasClient, "create_static_qr_code", mock_create_qr)

    with patch("integrations.bank.asaas.static_qr.save_pix_qr_png", return_value=None):
        asaas_static_qr.create_pix_qr(amount=Decimal("5.00"), payment_id=pid)

    with pytest.raises(asaas_static_qr.StaticQrError, match="payment_id_already_exists"):
        asaas_static_qr.create_pix_qr(amount=Decimal("5.00"), payment_id=pid)


@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_create_pix_qr_asaas_error(monkeypatch):
    """Erro de rede no Asaas é convertido em StaticQrError."""
    async def mock_list_keys(self, params=None):
        return _mock_pix_keys_resp()

    async def mock_create_qr(self, payload):
        raise AsaasError(400, {"errors": [{"code": "invalid_key"}]})

    monkeypatch.setattr(AsaasClient, "list_pix_address_keys", mock_list_keys)
    monkeypatch.setattr(AsaasClient, "create_static_qr_code", mock_create_qr)

    with pytest.raises(asaas_static_qr.StaticQrError, match="asaas_static_qr_create_failed"):
        asaas_static_qr.create_pix_qr(amount=Decimal("5.00"), payment_id=f"sqr_fail_{uuid.uuid4().hex[:8]}")


# ──────────────────────────────────────────────────────────────
# Testes de Webhook
# ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_webhook_payment_received_static_pix_qr():
    """PAYMENT_RECEIVED em static_pix_qr deve disparar payment.paid e virar PAID."""
    pid = f"sqr_wh_{uuid.uuid4().hex[:8]}"
    Payment.objects.create(
        payment_id=pid,
        kind=Payment.Kind.STATIC_PIX_QR,
        billing_type="PIX",
        qrcode_payload=TEST_QR_PAYLOAD,
        amount=Decimal("5.00"),
        status="PENDING",
        asaas_id=TEST_QR_ID,
    )

    payload = {
        "event": "PAYMENT_RECEIVED",
        "payment": {
            "id": TEST_QR_ID,
            "externalReference": pid,
            "status": "RECEIVED",
            "billingType": "PIX",
        },
    }

    with patch("core.hooks.dispatch", return_value=True) as mock_dispatch:
        row = asaas_webhooks.handle_event(payload)

    payment = Payment.objects.get(payment_id=pid)
    assert payment.status == "PAID"
    mock_dispatch.assert_called_once()
    call_kwargs = mock_dispatch.call_args[1]
    assert call_kwargs["provider"] == "asaas"
    assert call_kwargs["provider_payment_id"] == pid


@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_webhook_charge_payment_still_works():
    """PAYMENT_RECEIVED em kind=charge continua funcionando (compatibilidade)."""
    from integrations.bank.asaas.models import Customer

    pid = f"pay_charge_wh_{uuid.uuid4().hex[:8]}"
    cust, _ = Customer.objects.get_or_create(
        asaas_id="cus_compat_001",
        defaults={"name": "Compat", "cpf_cnpj": "12345678909"},
    )
    Payment.objects.create(
        payment_id=pid,
        kind=Payment.Kind.CHARGE,
        billing_type="PIX",
        customer=cust,
        amount=Decimal("5.00"),
        status="PENDING",
        asaas_id=f"pay_asaas_{uuid.uuid4().hex[:8]}",
    )

    payload = {
        "event": "PAYMENT_RECEIVED",
        "payment": {
            "id": f"pay_asaas_{uuid.uuid4().hex[:8]}",
            "externalReference": pid,
            "status": "RECEIVED",
            "billingType": "PIX",
        },
    }

    with patch("core.hooks.dispatch", return_value=True):
        asaas_webhooks.handle_event(payload)

    payment = Payment.objects.get(payment_id=pid)
    assert payment.status == "PAID"


# ──────────────────────────────────────────────────────────────
# Teste de Integração: _fill_pix usa static_qr
# ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
@override_settings(ASAAS_API_KEY="test_key_pix_qr")
def test_fill_pix_uses_static_qr_not_charge(monkeypatch):
    """_fill_pix deve usar static_qr.create_pix_qr, não asaas_charge.create_charge."""
    from integrations.bank.asaas import static_qr as asaas_static_qr
    import integrations.bank.asaas.charge as asaas_charge
    import users.roles.lead.service as lead_service
    from unittest.mock import MagicMock

    fill_pix_called_with = []

    def fake_create_pix_qr(**kwargs):
        fill_pix_called_with.append(kwargs)
        pid = kwargs.get("payment_id", f"sqr_{uuid.uuid4().hex[:8]}")
        return Payment.objects.create(
            payment_id=pid,
            kind=Payment.Kind.STATIC_PIX_QR,
            billing_type="PIX",
            qrcode_payload="00020126_payload_test",
            pix_qr_image=TEST_QR_IMAGE,
            amount=kwargs.get("amount", Decimal("5.00")),
            status="PENDING",
            asaas_id=TEST_QR_ID,
        )

    def fake_create_charge(**kwargs):
        raise AssertionError("create_charge NÃO deve ser chamado no fluxo PIX estático!")

    monkeypatch.setattr(asaas_static_qr, "create_pix_qr", fake_create_pix_qr)
    monkeypatch.setattr(asaas_charge, "create_charge", fake_create_charge)

    checkout_mock = MagicMock()
    checkout_mock.lead.external_id.hex = "a" * 32
    checkout_mock.pk = 1
    checkout_mock.amount = Decimal("5.00")
    profile_mock = MagicMock()

    with patch("integrations.bank.asaas.qr.qr_url_for", return_value="http://example.com/qr.png"):
        with patch("users.roles.lead.service.checkout_links"):
            lead_service._fill_pix(checkout_mock, profile_mock)

    assert len(fill_pix_called_with) == 1, "create_pix_qr deve ter sido chamado"
    assert fill_pix_called_with[0]["amount"] == Decimal("5.00")
    assert checkout_mock.checkout_url is None
    assert checkout_mock.due_date is None
    assert checkout_mock.qrcode_payload == "00020126_payload_test"
