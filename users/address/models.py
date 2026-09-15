"""Address — entidade própria de endereço (CONVENTION §4: relação invertida).

Endereço NÃO pertence ao profile; é o `Profile` (e, depois, o `Hub`) que aponta pra um
`Address` via FK (`users/profiles/models.py`). Por isso este model não tem FK pra user/profile.

Nasce vazio no provisionamento do `auth` (todos os campos null) e é preenchido depois por
CEP (ViaCEP) + PATCH. Vive sob o app_label `users` (sub-pacote, igual auth/profiles/roles).
"""

from __future__ import annotations

from django.db import models


class Address(models.Model):
    """Um endereço brasileiro. Campos de conteúdo nullable (criado vazio, preenchido depois)."""

    zipcode = models.CharField("CEP", max_length=8, null=True, blank=True)
    street = models.CharField("logradouro", max_length=200, null=True, blank=True)
    number = models.CharField("número", max_length=20, null=True, blank=True)
    complement = models.CharField("complemento", max_length=100, null=True, blank=True)
    neighborhood = models.CharField("bairro", max_length=100, null=True, blank=True)
    city = models.CharField("cidade", max_length=100, null=True, blank=True)
    state = models.CharField("UF", max_length=2, null=True, blank=True)
    country = models.CharField("país", max_length=2, default="BR")
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_address"
        verbose_name = "endereço"
        verbose_name_plural = "endereços"

    def __str__(self) -> str:
        return f"address<{self.pk}:{self.zipcode or 'vazio'}>"
