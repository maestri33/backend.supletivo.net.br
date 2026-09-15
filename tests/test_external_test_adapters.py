from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db


@override_settings(APP_ENV="test", TEST_EXTERNAL_ADAPTERS=True)
def test_pix_dict_sintetico_nao_chama_asaas(monkeypatch):
    from integrations.bank.asaas import pixkey

    monkeypatch.setattr(
        pixkey,
        "_dict_lookup",
        lambda key: pytest.fail(f"Asaas real chamado para {key}"),
    )
    row = pixkey.validate_pix_key(
        key="52998224725", key_type="cpf", expected_document="52998224725"
    )
    assert row.holder_document == "52998224725"
    assert row.bank_name == "Banco Sintético E2E"


@override_settings(APP_ENV="staging", TEST_EXTERNAL_ADAPTERS=False)
def test_payout_sintetico_nunca_move_dinheiro(monkeypatch):
    from integrations.bank.asaas import payout

    async def fail_send(*args, **kwargs):
        pytest.fail("Payout real foi chamado")

    monkeypatch.setattr(payout, "_send", fail_send)
    row = payout.create_payout(
        amount=Decimal("10.00"), pix_key="52998224725", payment_id="e2e-safe"
    )
    assert row.status == "SUBMITTED"
    assert row.asaas_id == "test-e2e-safe"


@override_settings(
    APP_ENV="test", TEST_EXTERNAL_ADAPTERS=True, TEST_KYC_OUTCOME="approved"
)
def test_kyc_e_viacep_sinteticos_sao_deterministicos():
    from core import test_adapters

    assert test_adapters.kyc_result()[0] == "approved"
    assert test_adapters.viacep_lookup("01310-100")["street"] == "Avenida Paulista"
    assert test_adapters.viacep_lookup("99999-999") is None
