"""Hub — o POLO (CONVENTION §4: relação invertida `Hub → Address` por FK).

Um polo tem um endereço (FK→`users.Address`), uma **marca** (catálogo no `.env`, igual às roles —
NÃO `choices` fixo no model: a lista válida vive em `settings.HUB_BRANDS`, validada no `interface`)
e um **coordenador** (um promotor; FK→User, identifica o polo na captação — spec hub: "coordenador
(external_id)"). `is_default` marca o polo PADRÃO (fallback de captação: candidato sem `ref` cai nele).

`external_id` (UUID) é o id exposto na borda da API; a referência interna é FK de verdade (§4).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel


class Hub(ExternalIdModel):
    """Um polo. Endereço (FK), marca (catálogo `.env`) e coordenador (um promotor, FK→User)."""

    address = models.ForeignKey(
        "users.Address",
        on_delete=models.PROTECT,
        related_name="hubs",
    )
    brand = models.CharField("marca", max_length=32)
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coordinated_hubs",
    )
    is_default = models.BooleanField("padrão", default=False)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "hub"
        db_table = "hub_hub"
        verbose_name = "polo"
        verbose_name_plural = "polos"
        constraints = [
            # só pode existir UM polo padrão (o fallback de captação).
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="uniq_default_hub",
            )
        ]

    def __str__(self) -> str:
        return f"hub<{self.external_id}:{self.brand}>"
