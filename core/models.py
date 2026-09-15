"""Models base comuns do core (CONVENTION §2)."""

import uuid

from django.db import models


class ExternalIdModel(models.Model):
    """Base abstrata com o ÚNICO external_id de borda do projeto (CONVENTION §4).

    Todo model exposto na API herda daqui em vez de redeclarar o campo. `external_id` (UUID, imutável) é
    o id opaco da borda — nunca a PK. As relações INTERNAS continuam por FK de verdade; este campo só
    aparece na fronteira da API. Como é abstrato, cada filho ganha sua própria coluna idêntica — então
    quem já declarava o campo igual NÃO muda de schema.
    """

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class ValidationCheck(models.Model):
    """Registro persistente de teste/validação que a gente fez, com flag + horário.

    Pedido do Victor: todo teste que rodarmos fica salvo, com a respectiva flag, pra **rastrear no
    futuro** se algo der errado. Append-only (cada execução grava uma linha = histórico); o `/status/`
    de cada integração mostra o ÚLTIMO resultado por `(scope, name)`. Ex.: `scope=asaas`,
    `name=webhook_external`, `passed=True`, `mode=artificial` (testado via link externo, ainda não por
    evento real do Asaas).
    """

    scope = models.CharField(max_length=64, db_index=True)  # ex.: asaas
    name = models.CharField(max_length=128, db_index=True)  # ex.: webhook_external
    passed = models.BooleanField()
    mode = models.CharField(max_length=32, blank=True)  # artificial | real | link | ...
    detail = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["scope", "name", "-checked_at"])]

    def __str__(self):
        flag = "OK" if self.passed else "FAIL"
        return f"{self.scope}:{self.name}={flag} @ {self.checked_at:%Y-%m-%d %H:%M}"


class PlatformSetting(models.Model):
    """Configurações dinâmicas da plataforma (preços, comissões, chaves, bootstrap).

    Permite que o Boss / Staff configure via dashboard parâmetros operacionais,
    com fallback seguro para o core/settings.py caso o campo não esteja no banco.
    """

    key = models.CharField(max_length=64, unique=True, db_index=True)
    value = models.TextField(blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")
    is_secret = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração da Plataforma"
        verbose_name_plural = "Configurações da Plataforma"
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}={self.value if not self.is_secret else '***'}"

