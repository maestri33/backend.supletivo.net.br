"""Candidate — 1ª role do funil do COLABORADOR (aspirante a promotor).

Espelho do enrollment do aluno (mesma coleta), com requisitos próprios: **Pix validada no DICT** + selfie.
Nasce do `register` (role `candidate`) **ligado a um HUB** (regra dura: candidato↔hub; sem `hub` → padrão).
Selfie validada → vira **training**. Sub-pacote de `users` (app_label `users`, 1 migration set; CONVENTION §2).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel
from users.roles._selfie import SelfieStatus


class Candidate(ExternalIdModel):
    """Um candidato a promotor (1-1 com o User), ligado ao hub onde se cadastrou."""

    class Status(models.TextChoices):
        STARTED = "started", "iniciado"
        PROFILE = "profile", "perfil"
        ADDRESS = "address", "endereço"
        DOCUMENTS = "documents", "documentos"
        PIX = "pix", "chave pix"
        EDUCATION = "education", "escolaridade"
        SELFIE = "selfie", "selfie"
        COMPLETED = "completed", "concluído (aguardando aprovação do coordenador)"
        APPROVED = "approved", "aprovado (virou promotor)"
        REJECTED = "rejected", "rejeitado pelo coordenador"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate",
    )
    hub = models.ForeignKey(
        "hub.Hub",
        on_delete=models.PROTECT,
        related_name="candidates",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.STARTED,
        db_index=True,
    )

    class DocType(models.TextChoices):
        """Tipo de documento que o candidato escolheu subir (plan/15 B).

        Fixado quando ele sobe a 1ª foto (`upload_document_photo`); a validação IA + extração
        miram o tipo escolhido. Imutável depois (`DOC_TYPE_LOCKED` no orquestrador)."""

        RG = "rg", "RG"
        CNH = "cnh", "CNH"

    # tipo de documento escolhido pelo candidato (plan/15 B). Definido quando ele sobe a 1ª
    # foto do documento (`upload_document_photo`); a validação IA + extração miram o tipo.
    doc_type = models.CharField(
        max_length=4,
        choices=DocType.choices,
        null=True,
        blank=True,
        db_index=True,
    )
    # identidade (filiação/estado civil/naturalidade/nacionalidade) + chave Pix → CENTRALIZADAS no
    # Profile (Victor 2026-06-16: a pessoa mora SÓ no Profile). Aqui fica só o flag de PROCESSO.
    pix_validated = models.BooleanField(default=False)
    # selfie (etapa selfie) — "assinar o contrato"; validação IA em 3 estados + revisão do coordenador.
    selfie_image = models.CharField(max_length=255, null=True, blank=True)
    selfie_taken_at = models.DateTimeField(
        null=True, blank=True, db_index=True
    )  # pro TTL do _analysis (plan/15 C)
    selfie_verified = models.BooleanField(
        default=False
    )  # = selfie_status aprovado (compat)
    selfie_status = models.CharField(
        max_length=20,
        choices=SelfieStatus.choices,
        default=SelfieStatus.PENDING,
        db_index=True,
    )
    selfie_description = models.TextField(
        null=True, blank=True
    )  # justificativa da IA/coordenador
    # contador de reprovações da selfie (F2): 5× → sobe `Profile.selfie_needs_meeting` (não bloqueia).
    selfie_reject_count = models.PositiveSmallIntegerField(default=0)
    # consentimento LGPD (lane #6): a selfie É a assinatura — gravamos o aceite no ato dela.
    # Registra QUAL versão/hash do contrato (users/consent) foi aceita + IP/UA/timestamp (prova).
    consent_accepted = models.BooleanField(default=False)
    contract_version = models.CharField(max_length=32, null=True, blank=True)
    contract_hash = models.CharField(max_length=64, null=True, blank=True)
    consent_ip = models.CharField(max_length=64, null=True, blank=True)
    consent_user_agent = models.TextField(null=True, blank=True)
    consent_accepted_at = models.DateTimeField(
        "consentimento aceito em", null=True, blank=True
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_candidate"
        verbose_name = "candidato"
        verbose_name_plural = "candidatos"

    def __str__(self) -> str:
        return f"candidate<{self.external_id}:{self.status}>"
