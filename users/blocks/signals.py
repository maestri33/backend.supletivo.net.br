"""Signals centralizados de ValidationBlock — UM ponto que ouve rejeição/resolução de TODOS os
models com status de validação: RG, CNH, AddressProof, StudentDocument (`validation_status`),
Enrollment e Candidate (`selfie_status`), Submission (`status` do treino).

Quando o status vira `rejected` → cria/atualiza bloco no User.
Quando vira `pending` (re-upload) ou `approved` → resolve o bloco daquela fonte.
Best-effort: erro no signal nunca quebra o save do model.

Conexão em `users/apps.py:UsersConfig.ready()`.
"""

from __future__ import annotations

import structlog

from users.blocks import service as blocks

logger = structlog.get_logger()

# ── mapeamento model → (como chegar no User, source_type, título) ──
# A action_route é resolvida por role (o mesmo doc-type existe em enrollment E candidate).


def _resolve_context(instance) -> tuple | None:
    """Devolve (user, source_type, title_prefix) ou None se não mapeado."""
    from users.documents.models import RG, CNH, AddressProof
    from users.roles.candidate.models import Candidate
    from users.roles.enrollment.models import Enrollment
    from users.roles.student.models import StudentDocument
    from users.roles.training.models import Submission

    if isinstance(instance, RG):
        return (instance.document.user, "rg", "Documento RG")
    if isinstance(instance, CNH):
        return (instance.document.user, "cnh", "Documento CNH")
    if isinstance(instance, AddressProof):
        return (instance.document.user, "address_proof", "Comprovante de endereço")
    if isinstance(instance, (Enrollment, Candidate)):
        # ponytail: a selfie mora no `selfie_status` (Enrollment e Candidate) — trata igual validation_status.
        return (instance.user, "selfie", "Selfie")
    if isinstance(instance, StudentDocument):
        return (
            instance.student.user,
            instance.doc_type,
            instance.get_doc_type_display(),
        )
    if isinstance(instance, Submission):
        # ponytail: source_type inclui o material_id pra distinguir atividades.
        return (instance.user, f"training_{instance.material_id}", "Atividade")
    return None


def _read_status(instance) -> str | None:
    """Lê o status relevante: `validation_status` pra docs, `selfie_status` pra enrollment, `status` pra Submission."""
    return (
        getattr(instance, "validation_status", None)
        or getattr(instance, "selfie_status", None)
        or getattr(instance, "status", None)
    )


_ENROLLMENT_ROUTES = {
    "rg": "/enrollment/documents/rg",
    "cnh": "/enrollment/documents",
    "address_proof": "/enrollment/address",
}


def _route_for(user, source_type: str) -> str:
    """Rota do frontend conforme a role ATIVA do usuário (a primeira que casar)."""
    from users.roles import interface as roles

    active = roles.active_roles(user)
    if "enrollment" in active:
        return _ENROLLMENT_ROUTES.get(source_type, "/enrollment")
    if "candidate" in active:
        return (
            "/candidate/address"
            if source_type == "address_proof"
            else "/candidate/document"
        )
    if "student" in active:
        return "/student/documents"  # todo doc do student cai na mesma tela
    return "/enrollment"


def _on_validation_change(sender, instance, **kwargs) -> None:
    """post_save: `validation_status`/`selfie_status` mudou → cria ou resolve bloco."""
    status = _read_status(instance)
    if status is None:
        return

    ctx = _resolve_context(instance)
    if ctx is None:
        return

    user, source_type, title_prefix = ctx

    if status == "rejected":
        reason = (
            (getattr(instance, "validation_result", None) or {}).get("reason")
            or getattr(instance, "justification", None)
            or getattr(instance, "selfie_description", None)
        )
        try:
            blocks.create_block(
                user=user,
                source_type=source_type,
                title=f"{title_prefix} reprovado",
                description=(reason or "").strip()
                or "Reenvie o documento para continuar.",
                action_label="Corrigir",
                action_route=_route_for(user, source_type),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "block.signal_create_failed",
                instance_id=getattr(instance, "id", None),
                source_type=source_type,
                user_id=user.id,
                error=str(exc),
            )

    elif status in ("pending", "approved"):
        # ponytail: re-upload (pending) ou aprovação (approved) — ambos resolvem o bloco.
        try:
            blocks.resolve_for_source(user=user, source_type=source_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "block.signal_resolve_failed",
                instance_id=getattr(instance, "id", None),
                source_type=source_type,
                user_id=user.id,
                error=str(exc),
            )
