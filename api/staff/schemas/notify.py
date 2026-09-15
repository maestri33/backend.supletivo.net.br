"""Schemas Pydantic v2 do grupo Staff: Mensageria, Notificações e TTS."""

from __future__ import annotations

from typing import Any

from ninja import Field, Schema


class TemplatePatchIn(Schema):
    title: str | None = None
    subject: str | None = None
    body_md: str | None = None
    is_tts: bool | None = None
    channels: str | None = None
    media_url: str | None = None
    media_type: str | None = None
    mail_template: str | None = None
    notes: str | None = None


class PreviewIn(Schema):
    ctx: dict[str, Any] | None = None


class TestIn(Schema):
    channels: list[str] | None = None
    ctx: dict[str, Any] | None = None


class AiAssistIn(Schema):
    text: str
    action: str = "improve"  # improve | simplify | shorten | fix | custom
    custom_prompt: str | None = None


class AiAssistOut(Schema):
    text: str
    action: str


class NotifyTriggerOut(Schema):
    fires_on: str = ""
    source: str | None = None
    delay_minutes: int = 0
    active: bool = True


class NotifyTemplateOut(Schema):
    event: str
    external_id: str
    title: str | None = None
    subject: str | None = None
    body_md: str | None = None
    is_tts: bool = False
    channels: str = "whatsapp,email"
    media_url: str | None = None
    media_type: str | None = None
    mail_template: str = "default"
    notes: str | None = None
    updated_at: str = "2026-08-19T00:00:00Z"
    trigger: NotifyTriggerOut | None = None


class NotifyTemplateStatsOut(Schema):
    total: int
    active: int
    inactive: int
    with_tts: int
    with_media: int
    by_channel: dict[str, int] = Field(default_factory=dict)


class NotifyEventOut(Schema):
    event: str
    has_template: bool
    has_in_memory: bool
    active: bool


class NotifyPreviewOut(Schema):
    event: str
    body_md: str
    rendered: str
    is_tts: bool
    channels: list[str] = Field(default_factory=list)


class NotifyTestOut(Schema):
    external_id: str


class NotifyHistoryItemOut(Schema):
    external_id: str | None = None
    caller: str | None = None
    recipient_phone: str | None = None
    recipient_email: str | None = None
    title: str | None = None
    subject: str | None = None
    text: str = ""
    want_whatsapp: bool = False
    want_email: bool = False
    want_tts: bool = False
    whatsapp_status: str | None = None
    email_status: str | None = None
    tts_status: str | None = None
    whatsapp_error: str | None = None
    email_error: str | None = None
    tts_error: str | None = None
    attempts: int = 0
    idempotency_key: str | None = None
    created_at: Any | None = None


class TtsOptionOut(Schema):
    model: str
    voice_female: str
    voice_male: str


class TtsConfigOut(Schema):
    omniroute_url: str
    chain: list[TtsOptionOut] = Field(default_factory=list)
    cross_gender_rule: str = "Destinatário Homem (M) recebe voz feminina; Mulher (F) recebe voz masculina."


class TtsProbeIn(Schema):
    text: str = "Olá, esta é uma mensagem de teste da síntese de voz Supletivo Brasil."
    gender: str | None = None  # "M", "F" ou None
    voice_override: str | None = None


class TtsProbeOut(Schema):
    ok: bool
    audio_url: str | None = None
    gender_target: str
    voice_used: str
    omniroute_url: str
    chain_results: list[dict[str, Any]] = Field(default_factory=list)
