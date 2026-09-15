"""Superfície de auditoria do módulo financeiro (Admin Sovereignty)."""

from __future__ import annotations

from typing import Any
import uuid

from django.db import transaction
from finance.models import FinancialAuditLog


def log_financial_audit(
    *,
    actor,
    action: str,
    target_model: str,
    target_external_id: uuid.UUID | str | None = None,
    justification: str,
    snapshot_before: dict[str, Any] | None = None,
    snapshot_after: dict[str, Any] | None = None,
) -> FinancialAuditLog:
    """Registra uma intervenção soberana do Admin no log de auditoria financeiro.

    Idempotente e seguro dentro ou fora de transações atômicas.
    Exige justification não vazia para garantir governança contábil.
    """
    if not (justification or "").strip():
        raise ValueError("justification_required")

    target_uuid = None
    if target_external_id:
        target_uuid = (
            uuid.UUID(str(target_external_id))
            if isinstance(target_external_id, str)
            else target_external_id
        )

    return FinancialAuditLog.objects.create(
        actor=actor,
        action=action,
        target_model=target_model,
        target_external_id=target_uuid,
        justification=justification.strip(),
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
    )


def list_financial_audit_logs(
    *,
    action: str | None = None,
    target_model: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Consulta os registros de auditoria financeira (mais recentes primeiro)."""
    qs = FinancialAuditLog.objects.select_related("actor").order_by("-created_at")
    if action:
        qs = qs.filter(action=action)
    if target_model:
        qs = qs.filter(target_model=target_model)

    results = []
    for log in qs[:limit]:
        results.append(
            {
                "external_id": str(log.external_id),
                "actor_external_id": str(log.actor.external_id) if log.actor else None,
                "action": log.action,
                "target_model": log.target_model,
                "target_external_id": str(log.target_external_id)
                if log.target_external_id
                else None,
                "justification": log.justification,
                "snapshot_before": log.snapshot_before,
                "snapshot_after": log.snapshot_after,
                "created_at": log.created_at.isoformat(),
            }
        )
    return results
