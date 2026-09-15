"""Promoter — fim do funil do COLABORADOR (candidato→treino→promotor).

Nasce quando o coordenador aprova a entrevista do treino. O `ref` de captação do lead **é o `external_id`
do User** (sem model de link — decisão `mvp-fluxo-roles`): a landing usa `?ref=<external_id do promotor>`.
Carrega o HUB herdado do candidato (promotor pertence a um polo). Sub-pacote de `users` (app_label `users`).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel


class Promoter(ExternalIdModel):
    """Um promotor ativo (1-1 com o User). Capta leads pelo link `?ref=<external_id>`."""

    class Status(models.TextChoices):
        ACTIVE = "active", "ativo"
        SUSPENDED = "suspended", "suspenso"  # não capta nem recebe

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="promoter",
    )
    hub = models.ForeignKey(
        "hub.Hub",
        on_delete=models.PROTECT,
        related_name="promoters",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    # pré-matriculado (Victor 2026-07-08): promotor SEM ensino médio completo. Abordagem diferenciada;
    # aos 3 leads pagos, entra sozinho no enrollment como BOLSISTA e a flag cai. Decidido no
    # `create_promoter` lendo `Profile.education_*` (F3).
    pre_matriculado = models.BooleanField("pré-matriculado (bolsa)", default=False)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_promoter"
        verbose_name = "promotor"
        verbose_name_plural = "promotores"

    def __str__(self) -> str:
        return f"promoter<{self.external_id}:{self.status}>"
