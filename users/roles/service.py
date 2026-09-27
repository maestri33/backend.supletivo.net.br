"""Lógica de roles — atribuição (entrada) e promoção (digivolução). Porte do legado p/ ORM Django.

Regras de transição vêm do catálogo do `.env` (`catalog`). A tabela `UserRole` guarda só quem tem
qual role agora + histórico (ativa = `revoked_at` nulo). Referência por FK ao User (§4).
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from users.exceptions import Conflict, Forbidden, NotFound, ValidationError
from users.roles import catalog
from users.roles.models import UserRole


def _active_qs(user):
    return UserRole.objects.filter(user=user, revoked_at__isnull=True)


def _bump_token_version(user) -> None:
    """Incrementa a versão de token do User → invalida todo JWT antigo. Chamado em TODA troca de role
    (assign/promote): a role mudou, o token velho cai e força re-login/refresh (Victor 2026-06-05)."""
    from django.db.models import F

    type(user).objects.filter(pk=user.pk).update(token_version=F("token_version") + 1)


def active_roles(user) -> list[str]:
    """Roles ativas do usuário (ordenadas)."""
    return sorted(_active_qs(user).values_list("role", flat=True))


def assign(user, role: str) -> list[str]:
    """Atribui uma role de ENTRADA (regra com from_role=None). Aditiva. Devolve as ativas."""
    rule = catalog.find_rule(to_role=role, from_role=None)
    if not rule:
        any_rule = catalog.find_any_rule(role)
        if any_rule and any_rule.mode == "replace":
            raise ValidationError(
                f"Role '{role}' não pode ser atribuída diretamente — "
                f"é promoção a partir de '{any_rule.from_role}'.",
                code="INVALID_ROLE_ASSIGNMENT",
            )
        raise NotFound(
            f"Regra para role '{role}' não encontrada", code="ROLE_NOT_FOUND"
        )

    current = active_roles(user)

    if rule.requires_role and rule.requires_role not in current:
        raise ValidationError(
            f"Role '{role}' exige a role '{rule.requires_role}' ativa.",
            code="INVALID_ROLE_ASSIGNMENT",
        )
    if rule.forbids_role and rule.forbids_role in current:
        raise ValidationError(
            f"Role '{role}' é incompatível com a role '{rule.forbids_role}' ativa.",
            code="INVALID_ROLE_ASSIGNMENT",
        )
    if role in current:
        raise Conflict(f"Usuário já possui a role '{role}'.", code="ROLE_ALREADY_HELD")

    UserRole.objects.create(user=user, role=role)
    _bump_token_version(user)  # role mudou → invalida JWT antigo
    return active_roles(user)


def promote(user, to_role: str) -> list[str]:
    """Promove (mode=replace): revoga a from_role e adiciona a to_role. Devolve as ativas."""
    rule = catalog.find_promotion_rule(to_role)
    if not rule or not rule.from_role:
        raise ValidationError(
            f"Promoção para '{to_role}' não existe.", code="INVALID_ROLE_PROMOTION"
        )

    from_role = rule.from_role
    current = active_roles(user)

    if from_role not in current:
        raise ValidationError(
            f"Usuário não possui a role '{from_role}' ativa.",
            code="INVALID_ROLE_PROMOTION",
        )
    if rule.forbids_role and rule.forbids_role in current:
        raise ValidationError(
            f"Role '{to_role}' é incompatível com a role '{rule.forbids_role}' ativa.",
            code="INVALID_ROLE_PROMOTION",
        )
    if to_role in current:
        raise Conflict(
            f"Usuário já possui a role '{to_role}'.", code="ROLE_ALREADY_HELD"
        )

    with transaction.atomic():
        _active_qs(user).filter(role=from_role).update(revoked_at=timezone.now())
        UserRole.objects.create(user=user, role=to_role)
        _bump_token_version(user)  # role mudou → invalida JWT antigo
    return active_roles(user)


def grant(user, role: str) -> list[str]:
    """Adiciona uma role de OVERLAY (aditiva — ex.: `training`) SEM bump de token_version.

    Diferente de `assign`/`promote`: NÃO força re-login (Victor 2026-06-16). A trava do treino é lida
    do `/me` (estado do banco), não do JWT — o promotor não leva OTP toda vez que ganha/perde a role
    de treino. Idempotente (role já ativa = no-op). Validação de catálogo fica no caller."""
    if role in active_roles(user):
        return active_roles(user)
    try:
        with (
            transaction.atomic()
        ):  # savepoint: IntegrityError não quebra a transação externa
            UserRole.objects.create(user=user, role=role)
    except IntegrityError:
        # corrida: outra transação concedeu a MESMA role ativa (constraint de role ativa única) — no-op.
        pass
    return active_roles(user)


def revoke(user, role: str) -> list[str]:
    """Revoga uma role de OVERLAY (ex.: `training`) SEM bump de token_version. Preserva o histórico
    (revoked_at). Idempotente (role ausente = no-op). Par do `grant`."""
    _active_qs(user).filter(role=role).update(revoked_at=timezone.now())
    return active_roles(user)


def is_blocked(user) -> bool:
    """True se alguma role ativa for `blocking` (catálogo)."""
    active = active_roles(user)
    if not active:
        return False
    blocking = catalog.blocking_roles()
    return any(r in blocking for r in active)


def purge_funnel_user(
    *,
    user_external_id: str | None = None,
    lead_external_id: str | None = None,
    candidate_external_id: str | None = None,
    cpf: str | None = None,
    phone: str | None = None,
) -> dict:
    """APAGA por completo um usuário do FUNIL (lead e/ou candidato) — staff only, IRREVERSÍVEL.

    Resolve o User por qualquer identificador (user/lead/candidate external_id, cpf ou phone) e
    deleta a linha do User numa transação — o cascade leva Profile, Lead+Checkout, Candidate,
    Document+sub-docs, Enrollment, Student, OTPs, biometria, submissões etc. Libera CPF/telefone/
    e-mail pra um novo cadastro (uso típico: limpar registro de teste).

    Recusa quem passou de lead/candidato: staff (`PURGE_STAFF_FORBIDDEN`), coordenador de polo,
    promotor (tem Promoter/leads captados — FKs PROTECT) ou quem tem comissões/payouts
    (`USER_NOT_PURGEABLE` + `reason`). Arquivos de mídia órfãos ficam no disco (paths com token
    aleatório, não-enumeráveis) — aceitável pro caso de uso.
    """
    from django.contrib.auth import get_user_model

    from users.profiles import interface as profiles
    from users.roles.candidate.models import Candidate
    from users.roles.lead.models import Lead
    from users.roles.promoter.models import Promoter

    User = get_user_model()

    user = None
    if user_external_id:
        user = User.objects.filter(external_id=user_external_id).first()
    elif lead_external_id:
        lead = (
            Lead.objects.filter(external_id=lead_external_id)
            .select_related("user")
            .first()
        )
        user = lead.user if lead else None
    elif candidate_external_id:
        cand = (
            Candidate.objects.filter(external_id=candidate_external_id)
            .select_related("user")
            .first()
        )
        user = cand.user if cand else None
    elif cpf:
        p = profiles.find_by_cpf(cpf)
        user = p.user if p else None
    elif phone:
        p = profiles.find_by_phone(phone)
        user = p.user if p else None
    else:
        raise ValidationError(
            "Informe um identificador: user_external_id, lead_external_id, "
            "candidate_external_id, cpf ou phone.",
            code="MISSING_FIELD",
        )
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    if user.is_superuser or user.is_staff:
        raise Forbidden(
            "Usuário de staff não pode ser apagado por aqui.",
            code="PURGE_STAFF_FORBIDDEN",
        )

    def _refuse(reason: str):
        raise Conflict(
            "Usuário passou de lead/candidato — apague as dependências antes.",
            code="USER_NOT_PURGEABLE",
            extra={"reason": reason},
        )

    if user.coordinated_hubs.exists():
        _refuse("hub_coordinator")
    if Promoter.objects.filter(user=user).exists() or user.captured_leads.exists():
        _refuse("promoter")
    if user.enrollments_promoted.exists():
        _refuse("promoter")
    if user.commissions.exists() or user.payment_requests.exists():
        _refuse("has_finance_records")

    ext = str(user.external_id)
    with transaction.atomic():
        _total, by_model = user.delete()
    deleted = {label.rsplit(".", 1)[-1]: n for label, n in sorted(by_model.items())}
    return {"user_external_id": ext, "deleted": deleted}


def users_with_role(role: str) -> list:
    """Todos os Users com a `role` ATIVA (revoked_at nulo). Ex.: listar promotores. Ordenado por id."""
    from django.contrib.auth import get_user_model

    user_ids = UserRole.objects.filter(role=role, revoked_at__isnull=True).values_list(
        "user_id", flat=True
    )
    return list(get_user_model().objects.filter(id__in=user_ids).order_by("id"))


CANONICAL_ROLES = ("student", "promoter", "hub", "admin")


def resolve_user_roles_and_statuses(
    user, raw_roles: list[str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """Resolve os 4 papéis canônicos da plataforma ('student', 'promoter', 'hub', 'admin')
    e seus respectivos status operacionais:
    - student: 'lead' | 'enrollment' | 'active' | 'veteran'
    - promoter: 'candidate' | 'training' | 'active' | 'suspended'
    - hub: 'active' | 'review'
    - admin: 'active'
    """
    raw = set(raw_roles or [])
    if user:
        raw.update(active_roles(user))
        if getattr(user, "is_superuser", False):
            raw.add("admin")
            raw.add("staff")

    roles: list[str] = []
    statuses: dict[str, str] = {}

    def _rel(name: str):
        if not user:
            return None
        try:
            return getattr(user, name, None)
        except Exception:
            return None

    # 1. Aluno (student)
    student_obj = _rel("student")
    enrollment_obj = _rel("enrollment")
    lead_obj = _rel("lead")
    is_student = (
        student_obj is not None
        or enrollment_obj is not None
        or lead_obj is not None
        or any(r in raw for r in ("lead", "enrollment", "student", "veteran", "aluno"))
    )

    if is_student:
        roles.append("student")
        if student_obj is not None:
            if getattr(student_obj, "status", None) == "veteran" or "veteran" in raw:
                statuses["student"] = "veteran"
            else:
                statuses["student"] = "active"
        elif enrollment_obj is not None or "enrollment" in raw:
            statuses["student"] = "enrollment"
        elif "veteran" in raw:
            statuses["student"] = "veteran"
        elif "student" in raw:
            statuses["student"] = "active"
        else:
            statuses["student"] = "lead"

    # 2. Promotor (promoter)
    promoter_obj = _rel("promoter")
    candidate_obj = _rel("candidate")
    is_promoter = (
        promoter_obj is not None
        or candidate_obj is not None
        or any(r in raw for r in ("candidate", "training", "promoter", "promotor"))
    )

    if is_promoter:
        roles.append("promoter")
        if "training" in raw:
            statuses["promoter"] = "training"
        elif promoter_obj is not None:
            statuses["promoter"] = (
                "active" if getattr(promoter_obj, "is_active", True) else "suspended"
            )
        elif "promoter" in raw or "promotor" in raw:
            statuses["promoter"] = "active"
        elif candidate_obj is not None or "candidate" in raw:
            statuses["promoter"] = "candidate"
        else:
            statuses["promoter"] = "candidate"

    # 3. Coordenador de Polo / Hub (hub)
    is_hub = any(r in raw for r in ("coordinator", "hub", "polo", "coordenador"))
    if not is_hub and user:
        coordinated = _rel("coordinated_hubs")
        if coordinated is not None and coordinated.exists():
            is_hub = True

    if is_hub:
        roles.append("hub")
        statuses["hub"] = "active"

    # 4. Administrador (admin)
    is_admin = any(r in raw for r in ("admin", "staff", "superuser"))
    if not is_admin and user and getattr(user, "is_superuser", False):
        is_admin = True

    if is_admin:
        roles.append("admin")
        statuses["admin"] = "active"

    ordered_roles = [r for r in CANONICAL_ROLES if r in roles]
    return ordered_roles, statuses
