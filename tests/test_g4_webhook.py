"""G4 (#11 + #21) — o webhook não pode confirmar pagamento (Payment=PAID + resposta 200) quando o
efeito de negócio (comissão/matrícula) falhou. Antes: dispatch engolia a exceção do handler, a view
respondia 200, o Asaas não re-tentava → dinheiro recebido sem efeito, mascarado como sucesso.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_g4_dispatch_reraise_opcional():
    """dispatch() engole por padrão (compat); com reraise=True, propaga a exceção do handler."""
    from core import hooks

    def boom(**kw):
        raise RuntimeError("handler quebrou")

    hooks.register("test.g4.evt", boom)
    try:
        assert hooks.dispatch("test.g4.evt") is False  # default: engole
        with pytest.raises(RuntimeError):
            hooks.dispatch("test.g4.evt", reraise=True)
    finally:
        hooks._HOOKS["test.g4.evt"].remove(boom)


def test_g4_webhook_propaga_falha_do_handler(monkeypatch):
    """Cobrança PAID cujo handler falha: handle_event PROPAGA (→ view 500 → Asaas re-tenta), não
    engole e responde sucesso. O Payment fica PAID (commitado antes) pro retry re-dispatchar."""
    from core import hooks
    from integrations.bank.asaas import webhooks
    from integrations.bank.asaas.models import Payment

    Payment.objects.create(
        payment_id="chg_g4", kind=Payment.Kind.CHARGE, status="PENDING", amount=100
    )

    def boom(**kw):
        raise RuntimeError("efeito de negócio falhou")

    monkeypatch.setitem(hooks._HOOKS, "payment.paid", [boom])

    payload = {
        "event": "PAYMENT_CONFIRMED",
        "payment": {"externalReference": "chg_g4", "id": "a1"},
    }
    with pytest.raises(RuntimeError):
        webhooks.handle_event(payload)

    assert Payment.objects.get(payment_id="chg_g4").status == "PAID"


def test_g4_retry_redispatcha_payment_ja_pago(monkeypatch):
    """No retry o Payment já está PAID; o webhook deve RE-dispatchar (não pular por status_unchanged),
    pra que um efeito que falhou na 1ª entrega finalmente rode. O handler é idempotente."""
    from core import hooks
    from integrations.bank.asaas import webhooks
    from integrations.bank.asaas.models import Payment

    Payment.objects.create(
        payment_id="chg_g4b", kind=Payment.Kind.CHARGE, status="PAID", amount=100
    )

    calls = []

    def handler(**kw):
        calls.append(kw)
        return True

    monkeypatch.setitem(hooks._HOOKS, "payment.paid", [handler])

    payload = {
        "event": "PAYMENT_CONFIRMED",
        "payment": {"externalReference": "chg_g4b", "id": "a2"},
    }
    webhooks.handle_event(payload)

    assert len(calls) == 1, "Payment já PAID não re-dispatchou → retry ficaria preso"


def test_g4_21_savepoint_auto_enroll_nao_derruba_pagamento(monkeypatch):
    """#21: falha em maybe_auto_enroll_bolsista (efeito secundário do PROMOTOR) não pode reverter o
    pagamento do CLIENTE. credit_commission + create_from_lead do cliente devem sobreviver."""
    import uuid
    from unittest.mock import patch

    from users.auth.models import User
    from users.roles.lead import service as lead_service

    promoter_user = User.objects.create_user(external_id=uuid.uuid4())
    client = User.objects.create_user(external_id=uuid.uuid4())

    class _Lead:
        self_study = False
        promoter = promoter_user
        user = client
        external_id = uuid.uuid4()

    with (
        patch("users.roles.promoter.models.Promoter.objects") as pobj,
        patch("finance.interface.commissions.credit_commission") as credit,
        patch.object(lead_service.hub_iface, "hub_of", return_value=object()),
        patch("users.roles.enrollment.service.create_from_lead") as create_enr,
        patch(
            "users.roles.promoter.service.maybe_auto_enroll_bolsista",
            side_effect=RuntimeError("auto-enroll do promotor explodiu"),
        ),
    ):
        pobj.filter.return_value.exists.return_value = False  # promotor ativo
        # não deve levantar: o savepoint isola a falha do auto-enroll
        lead_service._apply_effects(_Lead())

    assert credit.called, "comissão do cliente foi revertida pela falha do auto-enroll"
    assert create_enr.called, (
        "matrícula do cliente foi revertida pela falha do auto-enroll"
    )
