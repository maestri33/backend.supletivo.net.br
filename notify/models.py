"""Modelos de Template e Trigger de Notificações do V7M."""

from __future__ import annotations

import uuid
from django.db import models

_ALL_CHANNELS = {"whatsapp", "email"}


def _parse_channels(raw: str) -> list[str]:
    return [c.strip().lower() for c in raw.split(",") if c.strip().lower() in _ALL_CHANNELS]


class Template(models.Model):
    """Teor editável de uma notificação de evento de negócio."""

    external_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    event = models.SlugField(max_length=80, unique=True, db_index=True)

    title = models.CharField(max_length=200, null=True, blank=True)
    subject = models.CharField(max_length=255, null=True, blank=True)
    body_md = models.TextField(help_text="Markdown com placeholders {nome}, {link}, {valor}...")

    is_tts = models.BooleanField(default=False, help_text="Tenta voice-note; falha -> texto.")

    channels = models.CharField(max_length=40, default="whatsapp,email", help_text="Canais separados por vírgula.")
    media_url = models.CharField(max_length=500, null=True, blank=True)
    media_type = models.CharField(max_length=20, null=True, blank=True)
    mail_template = models.CharField(max_length=50, default="default", help_text="Slug do wrapper HTML.")

    notes = models.CharField(max_length=200, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "template de notificação"
        verbose_name_plural = "templates de notificação"

    def __str__(self):
        return f"Template({self.event})"

    @property
    def channel_list(self) -> list[str]:
        return _parse_channels(self.channels)


class Trigger(models.Model):
    """Regra de QUANDO o evento dispara."""

    external_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    template = models.OneToOneField(Template, on_delete=models.CASCADE, related_name="trigger")
    fires_on = models.CharField(max_length=200, blank=True, default="", help_text="Descrição humana do gatilho.")
    source = models.CharField(max_length=100, null=True, blank=True, help_text="Módulo/caller de origem.")
    delay_minutes = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "gatilho de notificação"
        verbose_name_plural = "gatilhos de notificação"

    def __str__(self):
        state = "ativo" if self.active else "inativo"
        return f"Trigger({self.template.event if hasattr(self, 'template') else self.template_id}, {state})"
