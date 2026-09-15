"""ValidationBlock — bloqueio do app: validação assíncrona rejeitou algo definitivamente.

Um bloco é uma flag que o frontend lê (polling) e exibe como modal bloqueante até o usuário
resolver a ação rejeitada. Criado automaticamente quando a IA (ou o coordenador, na decisão final)
rejeita um documento; resolvido quando o usuário re-envia o mesmo tipo de documento.

1 bloco ativo por (user, source_type) — UniqueConstraint garante.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class ValidationBlock(models.Model):
    """Bloqueio do app: validação assíncrona rejeitou algo → o usuário PRECISA resolver."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks",
    )
    source_type = models.CharField(
        "tipo da fonte rejeitada", max_length=64
    )  # rg_front, selfie, address_proof, id_card, ...
    source_external_id = models.CharField(
        "external_id da fonte", max_length=64, null=True, blank=True
    )
    title = models.CharField("título", max_length=200)
    description = models.TextField("descrição")
    action_label = models.CharField("rótulo da ação", max_length=100)
    action_route = models.CharField("rota da ação", max_length=200)
    resolved_at = models.DateTimeField("resolvido em", null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        app_label = "users"
        db_table = "users_validation_block"
        verbose_name = "bloqueio de validação"
        verbose_name_plural = "bloqueios de validação"
        indexes = [
            models.Index(fields=["user", "resolved_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "source_type"],
                condition=models.Q(resolved_at__isnull=True),
                name="uniq_active_block_per_source",
            ),
        ]

    def __str__(self) -> str:
        return f"block<{self.user_id}:{self.source_type}:{'resolved' if self.resolved_at else 'active'}>"
