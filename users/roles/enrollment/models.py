"""Enrollment — a 2ª role do funil do ALUNO (matrícula): nasce quando o LEAD PAGA.

Gatilho: o webhook do pagamento dispara o `hook` do lead (CONVENTION §7), que cria o Enrollment
**já ligado ao HUB herdado do promotor** (palavra do Victor 2026-06-04: ao virar matrícula, a
responsabilidade passa do promotor pro hub). Depois vem o funil de coleta (perfil→endereço→RG→dados
escolares→selfie até `awaiting_release`) e a liberação do coordenador (`awaiting_release`→student).

Sub-pacote de `users` (app_label `users`, 1 migration set — igual lead/address/documents; CONVENTION §2).
FK real (§4): `user` 1-1, `promoter` e `hub` por FK de verdade.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel
from users.roles._selfie import SelfieStatus


class Enrollment(ExternalIdModel):
    """A matrícula de um aluno (1-1 com o User). Carrega o hub herdado do promotor que indicou."""

    class Status(models.TextChoices):
        # status = a seção que o aluno preenche AGORA (vocabulário do wizard do front).
        # Ordem nova (plan/13, Victor 2026-06-11): DOCUMENTO primeiro — a extração povoa o
        # perfil (a etapa `started`/perfil morreu). Concluir uma seção avança pro NOME da próxima.
        RG = "rg", "RG (fotos + dados)"
        ADDRESS = "address", "endereço"
        EDUCATION = "education", "dados escolares"
        SELFIE = "selfie", "selfie (assinatura da matrícula)"
        AWAITING_RELEASE = "awaiting_release", "aguardando liberação"
        # fase da TAXA (plan/14, Victor 2026-06-12) — INTERNA do polo: o aluno NUNCA vê estas duas
        # (na visão dele aparecem como `awaiting_release` — política interna; máscara no service).
        FEE_PAID = "fee_paid", "1ª parcela da taxa paga"
        FEE_SCHEDULED = "fee_scheduled", "2ª parcela da taxa agendada"
        COMPLETED = "completed", "concluída"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollment",
    )
    # o promotor que captou o lead (snapshot — a obrigação dele acaba aqui; ganha a comissão no pagamento).
    promoter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="enrollments_promoted",
    )
    # HUB herdado do promotor: a partir da matrícula, é o hub (coordenador) que cuida do aluno.
    hub = models.ForeignKey(
        "hub.Hub",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    # auto-matrícula de promotor (herdado do lead): NÃO gera comissão (nem a veteran na formatura).
    self_study = models.BooleanField(default=False)
    # bolsista (Victor 2026-07-08): promotor pré-matriculado que atingiu 3 leads pagos. Carrega até o
    # Student — o teste final exige ≥10 leads pagos (soma com docs+sangue).
    bolsista = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RG,
        db_index=True,
    )
    # identidade (filiação/estado civil/naturalidade/nacionalidade) → CENTRALIZADA no Profile
    # (Victor 2026-06-16: a pessoa mora SÓ no Profile, nunca espalhada na matrícula).
    # selfie/ASSINATURA (etapa `selfie`, 6b) — foto em media/enrollment/<ext>/ + validação IA
    # 3 estados + revisão. `taken_at` = quando o aluno enviou (GET /selfie, plan/13).
    selfie_image = models.CharField(max_length=255, null=True, blank=True)
    selfie_taken_at = models.DateTimeField("selfie enviada em", null=True, blank=True)
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
        db_table = "users_enrollment"
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"

    def __str__(self) -> str:
        return f"enrollment<{self.external_id}:{self.status}>"


class EducationalData(models.Model):
    """Dados escolares coletados na matrícula (etapa `education`, 6b). 1-1 com o Enrollment.

    Estruturado (Victor 2026-06-20): nível + série (validada por nível) + flag de conclusão +
    escola/cidade/UF — é o dado mais valioso da matrícula (define a modalidade Fundamental×Médio
    e o que falta o aluno cursar). Campos nullable (criado vazio, preenchido no passo); a
    obrigatoriedade real é no schema da API + validação do service (`set_education`)."""

    class Level(models.TextChoices):
        FUNDAMENTAL = "fundamental", "Ensino Fundamental"
        MEDIO = "medio", "Ensino Médio"

    # faixa de série válida por nível: Fundamental 1–9, Médio 1–3 (usado em set_education)
    GRADE_RANGE = {"fundamental": (1, 9), "medio": (1, 3)}

    enrollment = models.OneToOneField(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="educational_data",
    )
    level = models.CharField(
        "nível", max_length=16, choices=Level.choices, null=True, blank=True
    )
    grade = models.PositiveSmallIntegerField("série/ano", null=True, blank=True)
    completed = models.BooleanField("concluiu o nível?", null=True, blank=True)
    last_school = models.CharField("qual escola", max_length=255, null=True, blank=True)
    city = models.CharField("cidade da escola", max_length=100, null=True, blank=True)
    state = models.CharField("UF da escola", max_length=2, null=True, blank=True)
    last_year_when = models.CharField("quando", max_length=64, null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_enrollment_education"
        verbose_name = "dados escolares"
        verbose_name_plural = "dados escolares"

    def __str__(self) -> str:
        return f"education<{self.enrollment_id}>"
