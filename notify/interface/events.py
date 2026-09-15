"""Despacho por evento; templates e triggers pertencem ao notify-server."""

from __future__ import annotations

import uuid

import structlog
from django.db import transaction

logger = structlog.get_logger()


def _name(value: str | None, *, full: bool = False) -> str | None:
    clean = " ".join((value or "").split())
    return clean if full else (clean.split()[0] if clean else None)


def _resolve_profile(user, profile):
    from users.profiles import interface as profiles

    if profile is not None and not hasattr(profile, "phone") and hasattr(profile, "external_id"):
        user = profile
        profile = None

    if profile is None and user:
        profile = getattr(user, "profile", None) or profiles.find_by_external_id(str(getattr(user, "external_id", user)))
    if profile is None:
        return None, None, None, None, None
    raw_name = getattr(profile, "name", None)
    return (
        _name(raw_name),
        _name(raw_name, full=True),
        getattr(profile, "phone", None) or None,
        getattr(profile, "email", None) or None,
        getattr(profile, "gender", None) or None,
    )


def send_event(
    event: str,
    *,
    user=None,
    profile=None,
    phone: str | None = None,
    email: str | None = None,
    ctx: dict | None = None,
    title: str | None = None,
    subject: str | None = None,
    media_url: str | None = None,
    media_type: str | None = None,
    gender: str | None = None,
    mail_template: str | None = None,
    idempotency_key: str | None = None,
    run_sync: bool = False,
    body_md_override: str | None = None,
    is_tts_override: bool | None = None,
    channels_override: tuple[str, ...] | list[str] | None = None,
) -> str | None:
    """Despacha notificação de evento renderizando o Template do banco local do backend."""
    from notify.interface import send as _send_iface
    from notify.interface import templates as _tpl_iface
    from notify.models import Trigger

    nome, nome_completo, p_phone, p_email, p_gender = _resolve_profile(user, profile)
    phone = phone or p_phone
    email = email or p_email

    if not phone and not email:
        logger.warning("notify.event_no_recipient", event_key=event)
        return None

    # 1. Verifica se o Trigger está desativado no banco do backend
    trigger = Trigger.objects.filter(template__event=event).first()
    if trigger is not None and not trigger.active:
        logger.info("notify.event_inactive", event_key=event)
        return None

    # 2. Busca e renderiza o Template do banco local
    tpl = _tpl_iface.get(event)
    if body_md_override is not None:
        body = body_md_override
        channels = list(channels_override) if channels_override is not None else (
            list(tpl.channels) if tpl is not None else ["whatsapp", "email"]
        )
        t_title = title or (tpl.title if tpl is not None else None)
        t_subject = subject or (tpl.subject if tpl is not None else None) or "Notificação"
        t_media_url = media_url or (tpl.media_url if tpl is not None else None)
        t_media_type = media_type or (tpl.media_type if tpl is not None else None)
        t_mail_tpl = mail_template or (tpl.mail_template if tpl is not None else None) or "default"
        t_is_tts = is_tts_override if is_tts_override is not None else (tpl.is_tts if tpl is not None else False)
    elif tpl is not None:
        render_ctx = {
            "nome": nome or "Olá",
            "nome_completo": nome_completo or nome or "Olá",
            "name": nome or "Olá",
        }
        if ctx:
            render_ctx.update(ctx)
        body = _tpl_iface.render(tpl.body_md, render_ctx)
        channels = list(channels_override) if channels_override is not None else list(tpl.channels)
        t_title = title or tpl.title
        t_subject = subject or tpl.subject
        t_media_url = media_url or tpl.media_url
        t_media_type = media_type or tpl.media_type
        t_mail_tpl = mail_template or tpl.mail_template
        t_is_tts = is_tts_override if is_tts_override is not None else tpl.is_tts
    else:
        logger.warning("notify.event_no_template", event_key=event)
        return None

    want_whatsapp = "whatsapp" in channels and bool(phone)
    want_email = "email" in channels and bool(email)
    if not want_whatsapp and not want_email:
        logger.warning("notify.event_no_active_channel", event_key=event)
        return None

    # Síntese de TTS realizada 100% no backend (com regra cruzada de gênero)
    if t_is_tts and not t_media_url and want_whatsapp:
        from integrations.ai import tts as _tts_module
        try:
            audio_url = _tts_module.synthesize_voice_note(
                body,
                gender=gender or p_gender,
                caller=f"event:{event}",
            )
            if audio_url:
                t_media_url = audio_url
                t_media_type = "audio"
        except Exception as exc:
            logger.warning("notify.backend_tts_error", event_key=event, error=str(exc))

    return _send_iface.send(
        text=body,
        caller=f"event:{event}",
        phone=phone,
        email=email,
        title=t_title,
        subject=t_subject,
        whatsapp=want_whatsapp,
        email_channel=want_email,
        tts=t_is_tts,
        media_url=t_media_url,
        media_type=t_media_type,
        gender=gender or p_gender,
        mail_template=t_mail_tpl or "default",
        idempotency_key=idempotency_key,
        run_sync=run_sync,
    )
