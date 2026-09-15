"""Guardas de dinheiro do TIER 1 da auditoria (G5, G6, G7). Cada teste reproduz o cenário exato
que a auditoria descreveu e verifica que a guarda fecha.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ───────────────────────── G5: webhook não rebaixa PAID ─────────────────────────
def test_g5_overdue_tardio_nao_rebaixa_paid():
    """PAYMENT_OVERDUE reentregue sobre uma cobrança já PAID não pode virar EXPIRED (travaria o
    reembolso). Só PENDING/EXPIRED -> PAID (pagamento tardio) é permitido."""
    from integrations.bank.asaas.models import Payment
    from integrations.bank.asaas.webhooks import _apply_charge

    pay = Payment.objects.create(
        payment_id="chg_g5",
        kind=Payment.Kind.CHARGE,
        status="PAID",
        amount=100,
    )
    payload = {"payment": {"externalReference": "chg_g5", "id": "asaas_1"}}
    row, reason = _apply_charge(payload, "PAYMENT_OVERDUE")
    pay.refresh_from_db()
    assert pay.status == "PAID", "PAID foi rebaixado por evento tardio"
    assert row is None and reason.startswith("terminal_")


def test_g5_pagamento_tardio_ainda_confirma():
    """Não-regressão: PENDING -> PAID (pagamento que chega depois) continua funcionando."""
    from integrations.bank.asaas.models import Payment
    from integrations.bank.asaas.webhooks import _apply_charge

    Payment.objects.create(
        payment_id="chg_g5b", kind=Payment.Kind.CHARGE, status="PENDING", amount=100
    )
    payload = {"payment": {"externalReference": "chg_g5b", "id": "a2"}}
    row, reason = _apply_charge(payload, "PAYMENT_CONFIRMED")
    assert row is not None and row.status == "PAID"


# ─────────────────── G6: comissão de fim de semana não some ───────────────────
def test_g6_comissao_de_semana_passada_entra_no_fechamento():
    """Comissão PENDING criada ANTES da janela desta semana (o caso do fim de semana) deve ser
    varrida pelo fechamento atual — antes ficava PENDING pra sempre."""
    from finance.interface.commissions import run_weekly_closing
    from finance.models import Commission, PaymentRequest
    from users.auth.models import User

    payee = User.objects.create_user(external_id=uuid.uuid4())
    c = Commission.objects.create(
        payee=payee,
        payee_role=Commission.Role.PROMOTER,
        source_type=Commission.Source.LEAD,
        source_external_id=uuid.uuid4(),
        amount=1,
        status=Commission.Status.PENDING,
    )
    # força o created_at pra 10 dias atrás (semana anterior), driblando o auto_now_add
    old = timezone.now() - timedelta(days=10)
    Commission.objects.filter(pk=c.pk).update(created_at=old)

    run_weekly_closing()

    c.refresh_from_db()
    assert c.status == Commission.Status.PROCESSED, "comissão atrasada ficou órfã"
    assert PaymentRequest.objects.filter(payee=payee).exists()


# ─────────────────── G7: promotor suspenso não recebe ───────────────────
def test_g7_suspenso_pula_comissao_ativo_credita():
    """`_apply_effects` de lead pago: promotor SUSPENSO → credit_commission NÃO é chamado; promotor
    ATIVO → é chamado. O resto do efeito (enrollment/hub) é mockado — só a guarda está sob teste."""
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

    def run(suspenso: bool) -> bool:
        with (
            patch("users.roles.promoter.models.Promoter.objects") as pobj,
            patch("finance.interface.commissions.credit_commission") as credit,
            patch.object(lead_service.hub_iface, "hub_of", return_value=object()),
            patch("users.roles.enrollment.service.create_from_lead"),
            patch("users.roles.promoter.service.maybe_auto_enroll_bolsista"),
        ):
            pobj.filter.return_value.exists.return_value = suspenso
            lead_service._apply_effects(_Lead())
            return credit.called

    assert run(suspenso=True) is False, "promotor suspenso recebeu comissão"
    assert run(suspenso=False) is True, "promotor ativo não recebeu comissão"


# ─────────── G-fee: duplo-submit de fee/pay não paga a taxa 2× (lock de linha) ───────────
def _enrollment_awaiting_release():
    """Matrícula real em `awaiting_release` (pronta pra 1ª parcela) + o coordenador do hub dela."""
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.roles.enrollment.models import Enrollment

    coord = User.objects.create_user(external_id=uuid.uuid4())
    promoter = User.objects.create_user(external_id=uuid.uuid4())
    student = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(city="São Paulo", state="SP")
    hub = Hub.objects.create(
        address=addr, brand="test", coordinator=coord, is_default=True
    )
    enr = Enrollment.objects.create(
        user=student,
        promoter=promoter,
        hub=hub,
        status=Enrollment.Status.AWAITING_RELEASE,
    )
    return coord, enr


# QR decode é REDE (Asaas); o fix sob teste é o LOCK, não o decode → planamos à vista R$50.
_PLAN_A_VISTA = {"amount": "50.00", "scheduled_for": None, "due_date": None}


def test_g_fee_pay_duplo_submit_enfileira_uma_vez(monkeypatch):
    """Dois POSTs de fee/pay pra mesma matrícula (o 2º serializado atrás do lock) resultam em UM
    único PaymentRequest — a ref determinística `_now` devolve o mesmo pedido, sem 2ª saída de R$."""
    from finance.models import PaymentRequest
    from users.roles.enrollment import service as es

    coord, enr = _enrollment_awaiting_release()
    monkeypatch.setattr(es, "_plan_fee_qr", lambda qr, amount=None: dict(_PLAN_A_VISTA))

    ext = str(enr.external_id)
    es.pay_fee(enrollment_external_id=ext, coordinator=coord, qr_code="qr")
    es.pay_fee(enrollment_external_id=ext, coordinator=coord, qr_code="qr")

    ref = f"fee_enr_{enr.external_id}_now"
    assert PaymentRequest.objects.filter(external_reference=ref).count() == 1, (
        "duplo-submit enfileirou a taxa 2×"
    )


def test_g_fee_pay_apos_confirmado_recusa_segundo(monkeypatch):
    """Depois que o webhook confirma PAID, o 2º submit é barrado (Conflict FEE_ALREADY_PAID) sob o
    lock — nunca uma 2ª fila. É o `first_paid` re-checado DENTRO do atomic."""
    from finance.models import PaymentRequest
    from users.exceptions import Conflict
    from users.roles.enrollment import service as es

    coord, enr = _enrollment_awaiting_release()
    monkeypatch.setattr(es, "_plan_fee_qr", lambda qr, amount=None: dict(_PLAN_A_VISTA))

    ext = str(enr.external_id)
    es.pay_fee(enrollment_external_id=ext, coordinator=coord, qr_code="qr")
    ref = f"fee_enr_{enr.external_id}_now"
    PaymentRequest.objects.filter(external_reference=ref).update(
        status=PaymentRequest.Status.PAID
    )

    with pytest.raises(Conflict):
        es.pay_fee(enrollment_external_id=ext, coordinator=coord, qr_code="qr")
    assert PaymentRequest.objects.filter(external_reference=ref).count() == 1


# ── pagamento avulso do staff: Idempotency-Key não dispara 2º PIX ──
def test_manual_payment_same_idempotency_key_dedups():
    """Mesma Idempotency-Key duas vezes → UM só PaymentRequest (mesma external_reference). Um retry
    do POST /finance/payments NÃO pode virar um 2º PIX de verdade."""
    from finance.interface import manual as finance_manual
    from finance.models import PaymentRequest

    key = str(uuid.uuid4())
    pr1 = finance_manual.request_pix_payment(
        amount="100", pix_key="a@b.com", idempotency_key=key
    )
    pr2 = finance_manual.request_pix_payment(
        amount="100", pix_key="a@b.com", idempotency_key=key
    )
    assert pr1.pk == pr2.pk, "retry criou um 2º pagamento"
    assert (
        PaymentRequest.objects.filter(external_reference=pr1.external_reference).count()
        == 1
    )


def test_manual_payment_different_keys_create_two():
    """Não-regressão: keys diferentes → dois pagamentos distintos."""
    from finance.interface import manual as finance_manual
    from finance.models import PaymentRequest

    finance_manual.request_pix_payment(
        amount="100", pix_key="a@b.com", idempotency_key=str(uuid.uuid4())
    )
    finance_manual.request_pix_payment(
        amount="100", pix_key="a@b.com", idempotency_key=str(uuid.uuid4())
    )
    assert PaymentRequest.objects.filter(kind=PaymentRequest.Kind.MANUAL).count() == 2
