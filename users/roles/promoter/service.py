"""Lógica do promoter (fim do funil do colaborador). Criado na aprovação da entrevista do treino.

`ref` de captação = o `external_id` do User (sem model de link). `validate_ref` é o que o funil do ALUNO
consome pra amarrar o lead ao promotor. Listagens (leads/comissões) são read-only sobre `lead`/`finance`.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

import structlog
from django.conf import settings
from django.utils import timezone

from users.blocks import service as blocks
from users.exceptions import (
    Conflict,
    Forbidden,
    IntegrationError,
    NotFound,
    ValidationError,
)
from users.roles.promoter.models import Promoter
from users.roles.promoter.rules import (
    BOLSA_ENROLL_THRESHOLD,
    get_bolsa_enroll_threshold,
    paid_referrals,
)

logger = structlog.get_logger()


def create_promoter(*, user, hub) -> Promoter:
    """Cria o Promoter(ACTIVE) ligado ao hub herdado do candidato. Idempotente.

    `pre_matriculado` (F4): promotor SEM ensino médio completo (lê `Profile.education_*`, F3) nasce
    com a flag — abordagem diferenciada; aos 3 leads pagos vira bolsista sozinho (`_maybe_auto_enroll`)."""
    from users.profiles import interface as profiles

    existing = Promoter.objects.filter(user=user).first()
    if existing is not None:
        return existing
    pre_matriculado = not profiles.has_medio_completo(user)
    promoter = Promoter.objects.create(
        user=user,
        hub=hub,
        status=Promoter.Status.ACTIVE,
        pre_matriculado=pre_matriculado,
    )
    logger.info(
        "promoter.created",
        external_id=str(promoter.external_id),
        hub=str(hub.external_id),
        pre_matriculado=pre_matriculado,
    )
    return promoter


def maybe_auto_enroll_bolsista(promoter_user) -> bool:
    """F4: promotor `pre_matriculado` que atingiu 3 leads pagos → auto-enroll como BOLSISTA, SEM
    pagamento (não cria Lead/Checkout). Chamado DENTRO da transação de `lead.mark_paid._apply_effects`,
    logo após creditar a comissão. Devolve True se converteu.

    Guard de corrida: o `.update(...)` condicional baixa a flag ATOMICAMENTE — se dois pagamentos do
    mesmo promotor caem juntos, só um toca a linha (1 row) e converte; o outro vê 0 e sai. Se ainda
    não bateu 3, restaura a flag e sai.
    """
    from users.roles import interface as roles
    from users.roles.enrollment import service as enrollment_iface
    from hub import interface as hub_iface

    flipped = Promoter.objects.filter(user=promoter_user, pre_matriculado=True).update(
        pre_matriculado=False
    )
    if not flipped:
        return False  # não era pré-matriculado (ou outra transação já pegou) → nada a fazer
    if paid_referrals(promoter_user) < get_bolsa_enroll_threshold():
        # ainda não chegou aos 3 → desfaz o flip e espera o próximo lead pago
        Promoter.objects.filter(user=promoter_user).update(pre_matriculado=True)
        return False
    hub = hub_iface.hub_of(promoter_user)
    if hub is None:
        Promoter.objects.filter(user=promoter_user).update(pre_matriculado=True)
        return False
    if "lead" not in roles.active_roles(promoter_user):
        roles.assign(promoter_user, "lead")
    enrollment_iface.create_from_lead(
        user=promoter_user,
        promoter=promoter_user,
        hub=hub,
        self_study=True,
        bolsista=True,
    )
    logger.info(
        "promoter.auto_enrolled_bolsista", external_id=str(promoter_user.external_id)
    )
    return True


def get_for_user(user) -> Promoter | None:
    return Promoter.objects.filter(user=user).select_related("hub").first()


def get_by_user_external_id(external_id: str) -> Promoter | None:
    return (
        Promoter.objects.filter(user__external_id=external_id)
        .select_related("user", "hub")
        .first()
    )


def validate_ref(ref: str):
    """`ref` = external_id do User-promotor ATIVO → devolve o User (o lead amarra nele); senão None.

    O `ref` chega CRU da landing (`?ref=`) — malformado (não-UUID) conta como inválido → None,
    NUNCA exceção solta (o caller cai no promotor padrão). Antes estourava 500 e quebrava o
    cadastro de quem clicou num link com ref estragado (bug reportado pelo Victor 2026-06-10)."""
    try:
        ref_uuid = uuid.UUID(str(ref))
    except (TypeError, ValueError):
        return None
    promoter = (
        Promoter.objects.filter(
            user__external_id=ref_uuid, status=Promoter.Status.ACTIVE
        )
        .select_related("user")
        .first()
    )
    if promoter is None:
        return None
    # promotor TRAVADO no treino obrigatório ainda NÃO capta (Victor 2026-06-16) — cai no padrão.
    from users.roles.training import service as training_iface

    if training_iface.is_locked(promoter.user):
        return None
    return promoter.user


def ref_url(user) -> str:
    base = (
        getattr(settings, "LANDING_BASE_URL", "") or settings.EXTERNAL_URL or ""
    ).rstrip("/")
    return f"{base}/?ref={user.external_id}"


def to_dict(promoter: Promoter) -> dict:
    """Painel do promotor. `locked` + `pending_materials` = a trava do treino (lida do banco, não do
    JWT): se travado, o front mostra só o treino. Liberado → painel cheio + captação ativa."""
    from users.profiles import interface as profiles
    from users.roles.training import service as training_iface
    from users.roles.candidate.models import Candidate
    from integrations.bank.asaas.models import PixKey

    profile = profiles.get(promoter.user)
    pix_key = profile.pix_key if profile else None
    pix_validated = bool(
        pix_key and PixKey.objects.filter(key=pix_key).exists()
    )

    cand = Candidate.objects.filter(user=promoter.user).first()
    docs_complete = cand.status in (Candidate.Status.APPROVED, Candidate.Status.COMPLETED) if cand else True

    missing = []
    if not pix_key:
        missing.append("pix_key")
    if cand and not docs_complete:
        missing.append("documents")

    payout_locked = len(missing) > 0
    profile_status = "ativo_pleno" if not payout_locked else "ativo_pendente"

    return {
        "external_id": str(promoter.external_id),
        "status": promoter.status,
        "hub_external_id": str(promoter.hub.external_id),
        "hub_brand": promoter.hub.brand if promoter.hub else "Supletivo Brasil Matriz",
        "ref_url": ref_url(promoter.user),
        "pre_matriculado": promoter.pre_matriculado,
        "locked": training_iface.is_locked(promoter.user),
        "pending_materials": training_iface.pending_materials(promoter.user),
        "blocks": [blocks.to_dict(b) for b in blocks.get_active_blocks(promoter.user)],
        "payout_locked": payout_locked,
        "profile_status": profile_status,
        "missing_requirements": missing,
        "name": profile.name if profile else None,
        "phone": profile.phone if profile else None,
        "pix_key": pix_key,
        "pix_validated": pix_validated,
    }


def detect_pix_key_type(key: str) -> str:
    """Detecta automaticamente o tipo canônico da chave PIX."""
    k = (key or "").strip()
    digits = "".join(ch for ch in k if ch.isdigit())
    if "@" in k:
        return "EMAIL"
    if len(k) == 36 and k.count("-") == 4:
        return "EVP"
    if len(digits) == 11 and (not k.startswith("+") and not k.startswith("55")):
        return "CPF"
    if len(digits) == 14:
        return "CNPJ"
    if k.startswith("+") or len(digits) in (12, 13) or (len(digits) in (10, 11) and not (len(k) == 11 and digits == k)):
        return "PHONE"
    return "EVP"


def set_promoter_pix(*, promoter: Promoter, key: str, key_type: str | None = None) -> dict:
    """Cadastra e valida a chave PIX do promotor no Asaas DICT com titularidade vinculada ao CPF do perfil."""
    from integrations.bank.asaas import pixkey
    from users.profiles import interface as profiles

    clean_key = (key or "").strip()
    if not clean_key:
        raise ValidationError("Chave PIX não pode ser vazia.", code="PIX_EMPTY")

    actual_key_type = key_type or detect_pix_key_type(clean_key)
    normalized_type = pixkey.normalize_key_type(actual_key_type)

    profile = profiles.get(promoter.user)
    if profile is None or not profile.cpf:
        raise ValidationError(
            "CPF do perfil ausente. Preencha seu cadastro antes de registrar a chave PIX.",
            code="PROFILE_CPF_MISSING",
        )

    try:
        validated_row = pixkey.validate_pix_key(
            key=clean_key,
            key_type=normalized_type,
            expected_document=profile.cpf,
        )
    except pixkey.PixKeyError as exc:
        raise ValidationError(
            f"Chave PIX inválida ou não pertence ao titular do CPF {profile.cpf}.",
            code="PIX_INVALID",
            extra={"reason": str(exc)},
        ) from exc

    profiles.set_pix(promoter.user.external_id, clean_key, normalized_type)
    logger.info(
        "promoter.pix_updated",
        promoter_external_id=str(promoter.external_id),
        pix_key=clean_key,
        key_type=normalized_type,
    )

    return {
        "pix_key": clean_key,
        "key_type": normalized_type,
        "bank_name": validated_row.bank_name,
        "holder_name": validated_row.holder_name,
        "validated": True,
    }


def test_promoter_pix(*, promoter: Promoter) -> dict:
    """Executa transferência real de R$ 0,01 para a chave PIX do promotor para validação bancária."""
    import secrets
    from decimal import Decimal
    from integrations.bank.asaas import payout as asaas_payout
    from users.profiles import interface as profiles

    profile = profiles.get(promoter.user)
    if profile is None or not profile.pix_key:
        raise ValidationError("Nenhuma chave PIX cadastrada para teste.", code="PIX_NOT_SET")

    payment_id = f"test-payout-{secrets.token_hex(6)}"
    try:
        res = asaas_payout.create_payout(
            amount=Decimal("0.01"),
            pix_key=profile.pix_key,
            payment_id=payment_id,
            description=f"Teste de Chave PIX - Promotor {profile.name or promoter.external_id}",
        )
        return {
            "success": True,
            "transfer_id": res.get("id"),
            "status": res.get("status"),
            "message": "PIX de teste de R$ 0,01 enviado com sucesso!",
        }
    except asaas_payout.PayoutError as exc:
        raise ValidationError(
            f"Falha ao enviar PIX de teste: {exc}",
            code="PIX_TEST_FAILED",
            extra={"error": str(exc)},
        ) from exc



def list_leads(user) -> list[dict]:
    """Leads captados por este promotor (read-only, do funil do aluno)."""
    from users.profiles import interface as profiles
    from users.roles.lead.models import Lead

    rows = list(
        Lead.objects.filter(promoter=user)
        .select_related("user")
        .order_by("-created_at")[:200]
    )
    pmap = profiles.get_map([row.user for row in rows])
    out = []
    for row in rows:
        p = pmap.get(row.user_id)
        out.append(
            {
                "external_id": str(row.external_id),
                "status": row.status,
                "name": p.name if p else None,
                "phone": p.phone if p else None,
                "created_at": row.created_at.isoformat(),
            }
        )
    return out


def invite_lead(*, promoter: Promoter, phone: str, cpf: str | None = None) -> dict:
    """Valida o destino e envia o link de indicação sem criar conta, Lead, cobrança ou OTP.

    `cpf` OPCIONAL (Victor 2026-07-28): o contrato do painel (A5.4/A7) é "iniciar matrícula
    com SÓ o telefone do aluno" — o promotor quase nunca tem o CPF na mão. Quando vier, segue
    validado e barrando duplicado; a barreira que importa (telefone já cadastrado) não muda."""
    from users.auth import service as auth_iface
    from users.auth import validation
    from users.profiles import interface as profiles
    from users.roles.training import service as training_iface

    if promoter.status != Promoter.Status.ACTIVE:
        raise Forbidden(
            "Promotor suspenso não pode enviar convites.", code="PROMOTER_SUSPENDED"
        )
    if training_iface.is_locked(promoter.user):
        raise Forbidden(
            "Conclua o treinamento antes de enviar convites.",
            code="PROMOTER_TRAINING_LOCKED",
        )

    if cpf:
        try:
            normalized_cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
        if not validation.cpf_check_digits_ok(normalized_cpf):
            raise ValidationError("CPF inválido.", code="CPF_INVALID")
        if profiles.exists_cpf(normalized_cpf):
            raise Conflict("CPF já cadastrado.", code="CPF_EXISTS")

    exists, normalized_phone = auth_iface.check_phone_whatsapp(phone)
    if profiles.exists_phone(normalized_phone):
        raise Conflict("Telefone já cadastrado.", code="PHONE_EXISTS")
    if not exists:
        raise ValidationError(
            "Telefone sem WhatsApp ativo.",
            code="PHONE_NOT_ON_WHATSAPP",
        )

    notification_id = _send_lead_invite(promoter.user, normalized_phone)
    if notification_id is None:
        raise IntegrationError(
            "Não foi possível encaminhar o convite.",
            code="INVITE_NOT_SENT",
        )
    return {"sent": True, "phone_last4": normalized_phone[-4:]}


def _send_lead_invite(promoter_user, phone: str) -> str | None:
    from notify.interface.send import send

    link = ref_url(promoter_user)
    digest = hashlib.sha256(
        f"{promoter_user.external_id}:{phone}".encode()
    ).hexdigest()[:20]
    day = timezone.localdate().isoformat()
    return send(
        text=(
            "Você recebeu um convite para conhecer o Supletivo Brasil.\n\n"
            f"Acesse com segurança pelo link: {link}\n\n"
            "Você confirma seus próprios dados antes de qualquer matrícula."
        ),
        caller="promoter.lead_invite",
        phone=phone,
        whatsapp=True,
        email_channel=False,
        tts=False,
        idempotency_key=f"promoter_lead_invite_{digest}_{day}",
    )


def list_commissions(user) -> list[dict]:
    """Comissões do promotor (read-only, do finance)."""
    from finance.models import Commission

    rows = Commission.objects.filter(payee=user).order_by("-created_at")[:200]
    return [
        {
            "external_id": str(row.external_id),
            "amount": str(row.amount),
            "source": row.source_type,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def summary(user) -> dict:
    """Resumo semanal + vitalício pro painel do promotor (`/promoter/me/summary`).

    Janela = a MESMA do fechamento (`week_window`, seg→seg SP). Contagens da semana NÃO filtram
    status: as comissões viram PROCESSED na sexta 18h e o contador zeraria no fim de semana.
    """
    from django.db.models import Sum

    from finance import config
    from finance.interface.commissions import next_closing_at, week_window
    from finance.models import Commission
    from users.roles.lead.models import Lead

    week_start, week_end = week_window()
    week_qs = Commission.objects.filter(
        payee=user, created_at__gte=week_start, created_at__lt=week_end
    )
    week_paid_leads = week_qs.filter(source_type=Commission.Source.LEAD).count()
    week_goal = config.bonus_threshold()
    week_total = week_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    lifetime_qs = Commission.objects.filter(payee=user)
    total_received = lifetime_qs.filter(status=Commission.Status.PAID).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_paid_leads": week_paid_leads,
        "week_goal": week_goal,
        "goal_reached": week_paid_leads >= week_goal,
        "week_commission_total": str(week_total),
        "bonus_amount": str(config.bonus_amount()),
        "next_closing_at": next_closing_at().isoformat(),
        "lifetime": {
            # self_study fora: é a matrícula do próprio promotor, não capta comissão.
            "total_students": Lead.objects.filter(
                promoter=user, status=Lead.Status.PAID, self_study=False
            ).count(),
            "goals_hit": lifetime_qs.filter(
                source_type=Commission.Source.BONUS
            ).count(),
            "total_received": str(total_received),
        },
    }


# ── coordenador: suspender / reativar / listar promotores do polo (WP5, Victor 2026-06-16) ──


def _coordinated_promoter(user_external_id: str, coordinator) -> Promoter:
    """Carrega o promotor (por external_id do User) e exige que `coordinator` coordene o hub dele."""
    promoter = get_by_user_external_id(user_external_id)
    if promoter is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")
    if promoter.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste promotor.", code="NOT_HUB_COORDINATOR"
        )
    return promoter


def suspend(*, user_external_id: str, coordinator) -> Promoter:
    """Coordenador suspende o promotor do polo (não capta nem recebe). Idempotente."""
    promoter = _coordinated_promoter(user_external_id, coordinator)
    if promoter.status != Promoter.Status.SUSPENDED:
        promoter.status = Promoter.Status.SUSPENDED
        promoter.save(update_fields=["status", "updated_at"])
        _notify_status(promoter, "promoter.suspended")
        logger.info("promoter.suspended", external_id=str(promoter.external_id))
    return promoter


def reactivate(*, user_external_id: str, coordinator) -> Promoter:
    """Coordenador reativa um promotor suspenso (volta a captar). Idempotente."""
    promoter = _coordinated_promoter(user_external_id, coordinator)
    if promoter.status != Promoter.Status.ACTIVE:
        promoter.status = Promoter.Status.ACTIVE
        promoter.save(update_fields=["status", "updated_at"])
        _notify_status(promoter, "promoter.reactivated")
        logger.info("promoter.reactivated", external_id=str(promoter.external_id))
    return promoter


def list_for_hub(hub) -> list[dict]:
    """Promotores do polo (pro painel do coordenador): status + se estão travados no treino."""
    from users.profiles import interface as profiles
    from users.roles.training import service as training_iface

    promoters = list(
        Promoter.objects.filter(hub=hub).select_related("user").order_by("created_at")
    )
    pmap = profiles.get_map([pr.user for pr in promoters])
    out = []
    for promoter in promoters:
        p = pmap.get(promoter.user_id)
        out.append(
            {
                "external_id": str(promoter.user.external_id),
                "name": p.name if p else None,
                "status": promoter.status,
                "locked": training_iface.is_locked(promoter.user),
            }
        )
    return out


def _notify_status(promoter: Promoter, event: str) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB.
    from users.profiles import interface as profiles
    from notify.interface.events import send_event

    p = profiles.get(promoter.user)
    try:
        send_event(
            event,
            profile=p,
            # chave por toggle (updated_at muda a cada mudança real de status) → retry dedupa, toggles não.
            idempotency_key=f"{event}_{promoter.user.external_id}_{int(promoter.updated_at.timestamp())}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "promoter.notify_status_failed", notify_event=event, error=str(exc)
        )
