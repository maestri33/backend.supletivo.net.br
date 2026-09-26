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
        from users.profiles import interface as profiles

        sp = profiles.get(user)
        s_name = (sp.name if sp and sp.name else None) or "Seu indicado"
        raw_phone = sp.phone if sp else None
        d = "".join(c for c in (raw_phone or "") if c.isdigit())
        if d.startswith("55") and len(d) in (12, 13):
            d = d[2:]
        fmt_phone = f"({d[:2]}) {d[2:7]}-{d[7:]}" if len(d) == 11 else (f"({d[:2]}) {d[2:6]}-{d[6:]}" if len(d) == 10 else (raw_phone or "-"))
        wa_digits = "".join(c for c in (raw_phone or "") if c.isdigit())
        if not wa_digits.startswith("55") and len(wa_digits) in (10, 11):
            wa_digits = "55" + wa_digits
        wa_url = f"https://wa.me/{wa_digits}" if wa_digits else ""

        send_event(
            "enrollment.concluded_referral",
            user=promoter,
            ctx={
                "aluno_nome": s_name,
                "student_name": s_name,
                "aluno_telefone": fmt_phone,
                "student_phone": fmt_phone,
                "aluno_whatsapp_url": wa_url,
                "student_external_id": str(instance.external_id),
            },
            idempotency_key=f"enr_concluded_promoter_{instance.external_id}",
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("student.notify_promoter_failed", student_id=instance.id)
