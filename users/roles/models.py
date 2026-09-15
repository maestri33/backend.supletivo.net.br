"""UserRole — quem tem qual role agora + histórico (CONVENTION §9).

O catálogo de transições (quais roles existem e como uma vira outra) NÃO mora aqui — mora no `.env`
(`ROLE_RULES`, lido por `users/roles/catalog.py`). Esta tabela guarda só as ATRIBUIÇÕES: cada linha
= uma role dada a um User. Ativa enquanto `revoked_at` é nulo; "digivolver" (mode=replace) revoga a
anterior e cria a nova → o histórico fica preservado nas linhas revogadas.

No monólito a referência é **FK de verdade** ao User (§4); a borda usa `external_id`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class UserRole(models.Model):
    """Uma role atribuída a um User. Ativa = `revoked_at IS NULL`."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roles",
    )
    role = models.CharField("papel", max_length=64)
    assigned_at = models.DateTimeField("atribuído em", auto_now_add=True)
    revoked_at = models.DateTimeField("revogado em", null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_user_role"
        verbose_name = "papel do usuário"
        verbose_name_plural = "papéis do usuário"
        indexes = [models.Index(fields=["user", "revoked_at"])]
        constraints = [
            # mesma role ativa não pode duplicar pro mesmo usuário (revoked_at NULL único).
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=models.Q(revoked_at__isnull=True),
                name="uniq_active_role_per_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role}"
