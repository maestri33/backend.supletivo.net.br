"""Interface de templates de notificação do backend (cache, getter e renderizador)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import structlog
from django.db.models.signals import post_delete, post_save

logger = structlog.get_logger()

_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_-]*)\}")
_CACHE_TTL_S = 30


@dataclass(frozen=True)
class TemplateData:
    """Snapshot imutável de um Template."""

    event: str
    title: str | None
    subject: str | None
    body_md: str
    is_tts: bool
    channels: tuple[str, ...]
    media_url: str | None
    media_type: str | None
    mail_template: str
    notes: str | None

    @classmethod
    def from_model(cls, t) -> TemplateData:
        return cls(
            event=t.event,
            title=t.title,
            subject=t.subject,
            body_md=t.body_md or "",
            is_tts=t.is_tts,
            channels=tuple(t.channel_list),
            media_url=t.media_url or None,
            media_type=t.media_type or None,
            mail_template=t.mail_template or "default",
            notes=t.notes or None,
        )


_CACHE: dict[str, tuple[TemplateData | None, float]] = {}
_SEED_CACHE: dict[str, TemplateData] = {}


def _get_seed_template(event: str) -> TemplateData | None:
    global _SEED_CACHE
    if not _SEED_CACHE:
        from pathlib import Path
        from notify.seed import io as seed_io

        for base in (
            Path(__file__).resolve().parents[1] / "seed" / "templates.md",
            Path(__file__).resolve().parents[2] / "seed" / "templates.md",
        ):
            if base.exists():
                specs = seed_io.parse(base.read_text(encoding="utf-8"))
                for s in specs:
                    _SEED_CACHE[s.event] = TemplateData(
                        event=s.event,
                        title=s.title,
                        subject=s.subject,
                        body_md=s.body_md or "",
                        is_tts=getattr(s, "is_tts", False),
                        channels=tuple(c.strip().lower() for c in s.channels.split(",") if c.strip()),
                        media_url=s.media_url or None,
                        media_type=s.media_type or None,
                        mail_template=s.mail_template or "default",
                        notes=None,
                    )
                break
    return _SEED_CACHE.get(event)


def _load(event: str) -> TemplateData | None:
    from notify.models import Template

    cached = _CACHE.get(event)
    if cached is not None and (time.monotonic() - cached[1]) < _CACHE_TTL_S:
        return cached[0]
    try:
        row = Template.objects.filter(event=event).first()
    except Exception as exc:
        logger.warning("notify.template_db_error", event_key=event, error=str(exc)[:160])
        return cached[0] if cached is not None else _get_seed_template(event)
    data = TemplateData.from_model(row) if row is not None else _get_seed_template(event)
    _CACHE[event] = (data, time.monotonic())
    return data


def get(event: str) -> TemplateData | None:
    return _load(event)


def invalidate(event: str | None = None) -> None:
    if event is not None:
        _CACHE.pop(event, None)
    else:
        _CACHE.clear()


def render(body: str, ctx: dict) -> str:
    """Substitui placeholders {chave} por ctx[chave]; ausentes ficam literais."""
    if not body:
        return ""

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        alias = key.replace("-", "_")
        if alias in ctx:
            return str(ctx[alias])
        alias_kebab = key.replace("_", "-")
        if alias_kebab in ctx:
            return str(ctx[alias_kebab])
        return m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, body)


def _on_template_change(sender, instance, **kwargs):
    invalidate(instance.event)


try:
    from notify.models import Template

    post_save.connect(_on_template_change, sender=Template, weak=False)
    post_delete.connect(_on_template_change, sender=Template, weak=False)
except Exception:
    pass
