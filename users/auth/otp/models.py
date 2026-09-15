"""Models do OTP — auditoria de cada código + estado do rate-limit (porte do legado).

`OtpCode`: registra cada operação de OTP (gerado/enviado/verificado/expirado/falho). O código em
texto plano NUNCA é persistido — só o hash SHA256 (compare_digest na verificação).
`OtpRateLimit`: substitui o Redis do legado (não temos Redis; Django-Q usa o banco). Uma linha por
User com a janela curta (1 a cada N s) e a janela horária (máx M/hora).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

STATUS_GENERATED = "generated"
STATUS_SENT = "sent"
STATUS_VERIFIED = "verified"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"


class OtpCode(models.Model):
    """Log/auditoria de um OTP. Plaintext nunca persiste — só `code_hash` (SHA256)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="otp_codes",
    )
    code_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default=STATUS_GENERATED)
    attempts = models.PositiveIntegerField(default=0)
    failure_reason = models.CharField(max_length=20, null=True, blank=True)
    # external_id (UUID) da notificação no notify (rastreia o despacho). Coluna solta em vez de
    # FK: no modo remote a Notification vive no notify-server, fora deste banco (Fase 2). UUIDField
    # porque send()/send_event() sempre devolvem str(uuid.uuid4()) nos dois modos (local e remote).
    notification_external_id = models.UUIDField(null=True, blank=True)
    error_detail = models.TextField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "users"
        db_table = "users_otp_code"
        indexes = [models.Index(fields=["user", "status", "created_at"])]

    def __str__(self) -> str:
        return f"otp<{self.user_id}:{self.status}>"


class OtpRateLimit(models.Model):
    """Estado de rate-limit por User (janela curta + janela horária). Substitui o Redis do legado."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="otp_rate_limit",
    )
    last_created_at = models.DateTimeField()
    hourly_count = models.PositiveIntegerField(default=0)
    hourly_window_start = models.DateTimeField()

    class Meta:
        app_label = "users"
        db_table = "users_otp_rate_limit"

    def __str__(self) -> str:
        return f"otp_rl<{self.user_id}>"
