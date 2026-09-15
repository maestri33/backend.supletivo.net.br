from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from finance import models as fin_models
from hub.models import Hub
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment.models import Enrollment
from users.exceptions import Conflict
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _require,
    get_by_external_id,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service
from users.roles.enrollment.coordinator import _notify_credentials, _notify_released
from users.roles.enrollment.fees_events import _fee_now_ref, _fee_due_ref, _notify_fee_event, fee_facts

def _enrollment_for_coordinator(
    enrollment_external_id: str, coordinator, *allowed_status
) -> Enrollment:
    """Carrega a matrícula e exige que o `coordinator` coordene o hub dela (gate de TODA ação plan/14)."""
    enr = get_by_external_id(enrollment_external_id)
    if enr is None:
        raise NotFound("Matrícula não encontrada.", code="ENROLLMENT_NOT_FOUND")
    if enr.hub.coordinator_id != coordinator.id:
        raise EnrollmentError(
            "Você não coordena o polo desta matrícula.", code="NOT_HUB_COORDINATOR"
        )
    if allowed_status and enr.status not in allowed_status:
        # visão do coordenador → status REAL (sem máscara).
        raise Conflict(
            "A matrícula está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": enr.status},
        )
    return enr


def _plan_fee_qr(qr_code: str, amount=None) -> dict:
    """Valida/decodifica o QR no Asaas (read-only, NÃO move dinheiro). QR ruim → erro de domínio."""
    from finance.interface import fees

    if not (qr_code or "").strip():
        raise EnrollmentError("Informe o QR code PIX da taxa.", code="FEE_QR_INVALID")
    try:
        return fees.plan_qr_payment(qr_payload=qr_code, amount=amount)
    except ValueError as exc:
        raise EnrollmentError(
            f"QR code inválido: {exc}", code="FEE_QR_INVALID"
        ) from exc


def _queue_fee(enr: Enrollment, *, qr_code: str, amount, scheduled_for, ref: str):
    """Enfileira (ou REENFILEIRA, se a tentativa anterior falhou) uma parcela na fila do finance."""
    from finance.interface import fees

    existing = fees.latest_fee_request(ref)
    if existing is not None and existing.status == fees.PaymentStatus.FAILED:
        # B.O. na tentativa anterior → o coordenador re-posta (até com QR novo) e a fila re-arma
        # com referência FRESCA (a falhada fica como auditoria; Asaas é idempotente por referência).
        return fees.retry_fee_payment(
            ref, qr_payload=qr_code, amount=amount, scheduled_for=scheduled_for
        )
    return fees.request_fee_payment(
        amount=amount,
        qr_payload=qr_code,
        supplier_name="credenciador",
        scheduled_for=scheduled_for,
        external_reference=ref,
        # relaciona a fee à matrícula (interno; o aluno NÃO sabe da taxa — palavra do Victor).
        source_type=fees.SourceType.ENROLLMENT,
        source_external_id=enr.external_id,
    )


def pay_fee(
    *, enrollment_external_id: str, coordinator, qr_code: str, amount=None
) -> dict:
    """1ª parcela (À VISTA): valida o QR e enfileira o PIX IMEDIATO (mesmo que o QR tenha vencimento —
    à vista é à vista; antecipação já provada real). O status do matriculado NÃO muda aqui: muda quando
    o pagamento CONFIRMAR PAGO (hook `fee.paid` → `fee_paid` — palavra do Victor 2026-06-12).
    Idempotente: repetir o POST não paga 2× (referência determinística `_now`)."""
    enr = _enrollment_for_coordinator(
        enrollment_external_id, coordinator, _S.AWAITING_RELEASE, _S.FEE_SCHEDULED
    )
    # fast-path: repost óbvio (webhook já confirmou) — poupa a rede antes de decodificar o QR.
    if fee_facts(enr)["first_paid"]:
        raise Conflict("A 1ª parcela desta taxa já está paga.", code="FEE_ALREADY_PAID")
    # decode do QR (REDE) FORA do atomic — não segura o lock de linha durante a chamada ao Asaas.
    plan = service._plan_fee_qr(qr_code, amount)
    with transaction.atomic():
        # Lock de linha na matrícula: serializa o duplo-submit CONCORRENTE. O 2º POST fica esperando o
        # 1º COMMITAR e só então re-checa/enfileira — aí já enxerga a fee na fila (ref determinística
        # `_now`) e devolve idempotente, em vez de correr pro INSERT e bater no unique(external_reference).
        # ponytail: a própria linha da matrícula é o mutex — sem tabela de idempotência nova.
        enr = Enrollment.objects.select_for_update().get(pk=enr.pk)
        if fee_facts(enr)["first_paid"]:
            raise Conflict(
                "A 1ª parcela desta taxa já está paga.", code="FEE_ALREADY_PAID"
            )
        pr = _queue_fee(
            enr,
            qr_code=qr_code,
            amount=plan["amount"],
            scheduled_for=None,
            ref=_fee_now_ref(enr),
        )
    logger.info(
        "enrollment.fee_pay_queued",
        external_id=str(enr.external_id),
        amount=str(pr.amount),
    )
    return {
        "external_id": str(enr.external_id),
        "status": enr.status,
        "fees": fee_facts(enr),
    }


def schedule_fee(
    *, enrollment_external_id: str, coordinator, qr_code: str, amount=None
) -> dict:
    """2ª parcela (AGENDADA): o vencimento vem de DENTRO do QR (cobrança com vencimento); QR sem
    vencimento → erro claro (não chuta data). O status muda NO ATO do agendamento → `fee_scheduled`
    (Victor 2026-06-12); QR já vencido → paga imediato (o vencimento chegou — semântica provada).
    NÃO depende da 1ª parcela estar paga — o que depende das duas é a CONCLUSÃO (palavra dele)."""
    enr = _enrollment_for_coordinator(
        enrollment_external_id, coordinator, _S.AWAITING_RELEASE, _S.FEE_PAID
    )
    if fee_facts(enr)["second_scheduled"]:
        raise Conflict(
            "A 2ª parcela desta taxa já está agendada.", code="FEE_ALREADY_SCHEDULED"
        )
    plan = service._plan_fee_qr(qr_code, amount)
    if plan["due_date"] is None:
        raise EnrollmentError(
            "Este QR não tem data de vencimento — pra agendar, use o QR da cobrança COM vencimento "
            "(ou pague à vista).",
            code="FEE_QR_NO_DUE_DATE",
        )
    pr = _queue_fee(
        enr,
        qr_code=qr_code,
        amount=plan["amount"],
        scheduled_for=plan["scheduled_for"],
        ref=_fee_due_ref(enr),
    )
    _set_status(enr, _S.FEE_SCHEDULED)
    _notify_fee_event(
        enr,
        "enrollment.fee_scheduled",
        valor=f"R$ {pr.amount}",
        due_date=plan["due_date"],
    )
    logger.info(
        "enrollment.fee_scheduled",
        external_id=str(enr.external_id),
        amount=str(pr.amount),
        due_date=plan["due_date"],
    )
    return {
        "external_id": str(enr.external_id),
        "status": enr.status,
        "fees": fee_facts(enr),
    }


def conclude(
    *,
    enrollment_external_id: str,
    coordinator,
    platform_login: str,
    platform_password: str,
    platform_url=None,
    platform_notes=None,
) -> Enrollment:
    """CONCLUSÃO (substitui o `release` antigo): com a 1ª parcela PAGA e a 2ª AGENDADA, o coordenador
    cadastra as credenciais da plataforma (fornecidas pela instituição — que só as libera com a 1ª paga)
    e o aluno vira student. Promoção ATÔMICA (role + COMPLETED + Student) — o miolo provado do release."""
    from users.roles.student import service as student_iface

    enr = _enrollment_for_coordinator(
        enrollment_external_id,
        coordinator,
        _S.AWAITING_RELEASE,
        _S.FEE_PAID,
        _S.FEE_SCHEDULED,
    )
    facts = fee_facts(enr)
    missing = []
    if not facts["first_paid"]:
        missing.append("first_fee_paid")
    if not facts["second_scheduled"]:
        missing.append("second_fee_scheduled")
    if missing:
        raise Conflict(
            "A taxa ainda não está completa pra concluir a matrícula.",
            code="FEES_INCOMPLETE",
            extra={"missing": missing},
        )

    # login da plataforma é ÚNICO por matrícula (Victor 2026-06-23) — rejeita ANTES de promover.
    student_iface.ensure_platform_login_available(
        platform_login=platform_login,
        exclude_user_external_id=str(enr.user.external_id),
    )

    with transaction.atomic():
        if "student" not in roles.active_roles(enr.user):
            roles.promote(enr.user, "student")
        enr.status = _S.COMPLETED
        enr.save(update_fields=["status", "updated_at"])
        student_iface.create_from_enrollment(
            user=enr.user,
            hub=enr.hub,
            self_study=enr.self_study,
            bolsista=enr.bolsista,
            platform_url=platform_url,
            platform_login=platform_login,
            platform_password=platform_password,
            platform_notes=platform_notes,
        )

    _notify_released(enr)
    _notify_credentials(enr, login=platform_login, password=platform_password)
    logger.info("enrollment.concluded", external_id=str(enr.external_id))
    return enr


