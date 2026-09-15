"""Signals do Student — notify o promoter quando um lead indicado vira aluno."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


def on_student_created(sender, instance, created: bool, **kwargs) -> None:
    """Promoção lead→student (primeira vez): notifica o promoter que indicou."""
    if not created:
        return
    from users.roles.lead.models import Lead

    user = instance.user
    lead = Lead.objects.filter(user=user).order_by("-created_at").first()
    if lead is None or lead.promoter_id is None:
        return
    promoter = lead.promoter
    try:
        from notify.interface.events import send_event

        send_event(
            "enrollment.concluded_referral",
            user=promoter,
            ctx={"student_external_id": str(instance.external_id)},
            body_md_override=f"Parabéns! Sua indicação concluiu a matrícula e virou aluno (ID: {instance.external_id}).",
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("student.notify_promoter_failed", student_id=instance.id)
