"""Superfície mínima do notify-server."""

from __future__ import annotations

import uuid

import structlog
from django.db import transaction

from users.exceptions import NotFound, ValidationError

logger = structlog.get_logger()

_MEDIA_EXT = {
    "image": {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"},
    "video": {"mp4", "mov", "avi", "mkv", "webm", "3gp"},
    "audio": {"mp3", "ogg", "wav", "m4a", "aac", "opus"},
}


def _guess_media_type(url: str) -> str:
    ext = url.rsplit("?", 1)[0].rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower()
    return next((kind for kind, exts in _MEDIA_EXT.items() if ext in exts), "document")


def send(
    *,
    text: str,
    caller: str,
    phone: str | None = None,
    email: str | None = None,
    title: str | None = None,
    subject: str | None = None,
    whatsapp: bool = True,
    email_channel: bool = False,
    tts: bool = False,
    media_url: str | None = None,
    media_type: str | None = None,
    gender: str | None = None,
    mail_template: str = "default",
    idempotency_key: str | None = None,
    run_sync: bool = False,
) -> str:
    """Envia pelo notify-server, síncrono quando pedido e via Django-Q no caso normal."""
    client_uuid = str(uuid.uuid4())
    payload = {
        "text": text,
        "caller": caller,
        "phone": phone,
        "email": email,
        "title": title,
        "subject": subject,
        "whatsapp": whatsapp,
        "email_channel": email_channel,
        "tts": tts,
        "media_url": media_url,
        "media_type": media_type or (_guess_media_type(media_url) if media_url else None),
        "gender": gender,
        "mail_template": mail_template,
        "external_id": idempotency_key or client_uuid,
        "run_sync": run_sync,
    }
    if run_sync:
        from notify.sdk import client

        return str(client.post_send(payload, run_sync=True)["external_id"])

    from django_q.tasks import async_task

    transaction.on_commit(lambda: async_task("notify.sdk.push.push_send", payload))
    logger.info("notify.remote_queued", external_id=client_uuid, caller=caller)
    return client_uuid


def send_adhoc(
    *,
    message: str,
    to_user: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    subject: str | None = None,
    channels: list[str] | None = None,
    caller: str = "notify.adhoc",
) -> str:
    message = (message or "").strip()
    if not message:
        raise ValidationError("Mensagem não pode ser vazia.", code="MISSING_FIELD")
    phone = (phone or "").strip() or None
    email = (email or "").strip().lower() or None
    if to_user:
        from users.profiles import interface as profiles

        profile = profiles.find_by_external_id(to_user)
        if profile is None:
            raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
        phone = phone or profile.phone or None
        email = email or profile.email or None
    if not phone and not email:
        raise ValidationError("Informe ao menos um destino.", code="MISSING_FIELD")
    requested = {c.strip().lower() for c in (channels or [])} or {"whatsapp", "email"}
    want_whatsapp = "whatsapp" in requested and bool(phone)
    want_email = "email" in requested and bool(email)
    if not want_whatsapp and not want_email:
        raise ValidationError("Nenhum canal possui destino válido.", code="MISSING_FIELD")
    return send(
        text=message,
        caller=caller,
        phone=phone if want_whatsapp else None,
        email=email if want_email else None,
        subject=subject,
        title=subject,
        whatsapp=want_whatsapp,
        email_channel=want_email,
    )
