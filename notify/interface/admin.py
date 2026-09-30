"""Módulo de Alertas Administrativos do Sistema Notify."""

from __future__ import annotations

import structlog
from django.conf import settings

logger = structlog.get_logger()


def notify_admin_alert(*, title: str, message: str, caller: str = "notify.system") -> None:
    """Dispara alerta transacional para o Super Admin (Victor) sobre falhas críticas ou anomalias."""
    from users.models import User
    from notify.interface import send as _send_iface

    admin = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    admin_prof = getattr(admin, "profile", None) if admin else None

    phone = (admin_prof.phone if admin_prof else None) or getattr(settings, "DEFAULT_STAFF_PHONE", None)
    email = (admin_prof.email if admin_prof else None) or getattr(settings, "DEFAULT_STAFF_EMAIL", None)

    if not phone and not email:
        logger.warning("notify.admin_alert_skipped_no_destination", title=title)
        return

    alert_text = (
        f"⚠️ *[ALERTA DE SISTEMA]*\n\n"
        f"📌 *{title}*\n\n"
        f"{message}\n\n"
        f"🔧 Origem: `{caller}`"
    )

    try:
        _send_iface.send(
            text=alert_text,
            caller=f"admin_alert:{caller}",
            phone=phone,
            email=email,
            title=f"Alerta: {title}",
            subject=f"[ALERTA NOTIFY] {title}",
            whatsapp=bool(phone),
            email_channel=bool(email),
            run_sync=False,
        )
        logger.info("notify.admin_alert_dispatched", title=title, phone=phone, email=email)
    except Exception as exc:
        logger.warning("notify.admin_alert_failed", title=title, error=str(exc))
