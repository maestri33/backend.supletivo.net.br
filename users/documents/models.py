"""Documents — agregado de documentos do usuário (spec documents; VISAO §serviços-de-apoio).

`Document` é a raiz, 1-1 com o `User`, criada no provisionamento do `auth`. Os sub-documentos
(`RG`, `CNH`, `Certificate`, `Military`) são 1-1 com o `Document` (carregam `document_id`, §4) e
nascem TODOS junto, com campos null — vão sendo preenchidos depois. Foto = path relativo no DB
(arquivo físico em `media/documents/<external_id>/<slot>.<ext>`).

Só RG/CNH/certidão/serviço-militar (palavra do dono) — WorkCard/Passport do legado ficam de fora.
Vive sob o app_label `users` (sub-pacote, igual auth/profiles/roles).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Document(models.Model):
    """Raiz dos documentos, 1-1 com o User. Criada (com sub-docs null) no provisionamento."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_document"
        verbose_name = "documento"
        verbose_name_plural = "documentos"

    def __str__(self) -> str:
        return f"document<{self.pk}>"


class RG(models.Model):
    """Carteira de identidade (RG). Todos os campos null (preenchidos depois).

    Validação por IA (plan/12): cada foto passa pela visão (é RG? legível?) e, com a seção completa,
    OCR + extração preenchem os campos sozinhos. 4 estados (espelha o student): pending/approved/
    rejected/review. `validation_result` guarda os vereditos por foto, os dados extraídos e a
    decisão humana (justificativa SEMPRE — plan/9)."""

    class Validation(models.TextChoices):
        PENDING = "pending", "aguardando IA"
        APPROVED = "approved", "aprovado"
        REJECTED = "rejected", "reprovado (refazer)"
        REVIEW = "review", "em revisão (coordenador decide)"

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="rg"
    )
    number = models.CharField("número", max_length=30, null=True, blank=True)
    issuing_agency = models.CharField(
        "órgão emissor", max_length=50, null=True, blank=True
    )
    issue_date = models.DateField("data de emissão", null=True, blank=True)
    front_photo = models.CharField("foto frente", max_length=500, null=True, blank=True)
    back_photo = models.CharField("foto verso", max_length=500, null=True, blank=True)
    # RG inteiro (frente+verso numa imagem só) — alternativa ao par front/back (plan/12).
    full_photo = models.CharField("foto inteira", max_length=500, null=True, blank=True)
    validation_status = models.CharField(
        "validação IA",
        max_length=20,
        choices=Validation.choices,
        default=Validation.PENDING,
        db_index=True,
    )
    validation_result = models.JSONField(
        "resultado da validação", null=True, blank=True
    )
    validated_at = models.DateTimeField("validado em", null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_rg"
        verbose_name = "RG"
        verbose_name_plural = "RGs"


class CNH(models.Model):
    """Carteira de habilitação (CNH) — porte do conjunto do legado (palavra do dono).

    Plan/15 B2 — `validation_status`/`validation_result`/`validated_at`/`full_photo` (espelho do RG;
    mesma máquina de 4 estados + aceite de CNH inteira numa foto só)."""

    class Validation(models.TextChoices):
        PENDING = "pending", "aguardando IA"
        APPROVED = "approved", "aprovado"
        REJECTED = "rejected", "reprovado (refazer)"
        REVIEW = "review", "em revisão (coordenador decide)"

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="cnh"
    )
    number = models.CharField("número", max_length=30, null=True, blank=True)
    category = models.CharField("categoria", max_length=5, null=True, blank=True)
    date_of_birth = models.DateField("data de nascimento", null=True, blank=True)
    expires_on = models.DateField("validade", null=True, blank=True)
    national_register = models.CharField(
        "registro nacional", max_length=30, null=True, blank=True
    )
    front_photo = models.CharField("foto frente", max_length=500, null=True, blank=True)
    back_photo = models.CharField("foto verso", max_length=500, null=True, blank=True)
    # CNH inteira (frente+verso numa imagem só) — alternativa ao par front/back (plan/15 B2,
    # espelhando `rg_full`).
    full_photo = models.CharField("foto inteira", max_length=500, null=True, blank=True)
    validation_status = models.CharField(
        "validação IA",
        max_length=20,
        choices=Validation.choices,
        default=Validation.PENDING,
        db_index=True,
    )
    validation_result = models.JSONField(
        "resultado da validação", null=True, blank=True
    )
    validated_at = models.DateTimeField("validado em", null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_cnh"
        verbose_name = "CNH"
        verbose_name_plural = "CNHs"


class Certificate(models.Model):
    """Certidão — nascimento/casamento/óbito; só UMA por document (1-1). Campos null."""

    KIND_CHOICES = (
        ("nascimento", "nascimento"),
        ("casamento", "casamento"),
        ("obito", "óbito"),
    )

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="certificate"
    )
    kind = models.CharField(
        "tipo", max_length=20, choices=KIND_CHOICES, null=True, blank=True
    )
    number = models.CharField("número", max_length=50, null=True, blank=True)
    registry_office = models.CharField(
        "cartório", max_length=100, null=True, blank=True
    )
    book = models.CharField("livro", max_length=20, null=True, blank=True)
    page = models.CharField("folha", max_length=20, null=True, blank=True)
    entry = models.CharField("termo", max_length=20, null=True, blank=True)
    issue_date = models.DateField("data de emissão", null=True, blank=True)
    photo = models.CharField("foto", max_length=500, null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_certificate"
        verbose_name = "certidão"
        verbose_name_plural = "certidões"


class AddressProof(models.Model):
    """Comprovante de residência (foto/PDF) — OBRIGATÓRIO + validado por IA (Victor 2026-07-08):
    confere se o endereço bate com o informado E o titular (sobrenome). Titular diferente NÃO reprova
    → `needs_kinship`: pede o grau de parentesco (cônjuge/pai/mãe...) e libera. Gateia a etapa endereço."""

    class Validation(models.TextChoices):
        PENDING = "pending", "aguardando IA"
        APPROVED = "approved", "aprovado"
        REJECTED = "rejected", "reprovado (refazer)"
        REVIEW = "review", "em revisão (coordenador decide)"
        NEEDS_KINSHIP = "needs_kinship", "aguardando explicação de parentesco"

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="address_proof"
    )
    photo = models.CharField("foto", max_length=500, null=True, blank=True)
    validation_status = models.CharField(
        max_length=20,
        choices=Validation.choices,
        default=Validation.PENDING,
        db_index=True,
    )
    validation_result = models.JSONField("resultado da IA", null=True, blank=True)
    validated_at = models.DateTimeField("validado em", null=True, blank=True)
    # titular diferente: quem é + grau de parentesco (texto livre — "não importa quem seja, mas temos
    # que saber pra não virar baderna", Victor).
    kinship_relation = models.CharField(
        "grau de parentesco do titular", max_length=200, null=True, blank=True
    )
    kinship_provided_at = models.DateTimeField(
        "parentesco informado em", null=True, blank=True
    )

    class Meta:
        app_label = "users"
        db_table = "users_document_address_proof"
        verbose_name = "comprovante de residência"
        verbose_name_plural = "comprovantes de residência"


class Military(models.Model):
    """Documento de serviço militar (reservista). Criado pra todos; só `gender='M'` preenche (Q4)."""

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="military"
    )
    number = models.CharField("número", max_length=30, null=True, blank=True)
    series = models.CharField("série", max_length=20, null=True, blank=True)
    category = models.CharField("categoria", max_length=20, null=True, blank=True)
    ra = models.CharField("RA", max_length=20, null=True, blank=True)
    photo = models.CharField("foto", max_length=500, null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_military"
        verbose_name = "documento militar"
        verbose_name_plural = "documentos militares"
