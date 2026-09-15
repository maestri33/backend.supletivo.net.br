"""Profile — dados pessoais/contato, 1-1 com o User (CONVENTION §4: "contato mora em profiles").

Unicidade absoluta de **cpf, phone, email** (§9) + `gender` (brinde do CPFHub; usado p/ voz do TTS
e doc de reservista). `profiles` COMPLETO (ciclo 3b 2026-06-01): `name` + `birth_date` (vêm do
CPFHub no register), `pix_key` (só o campo; validação Asaas/DICT adiada pro ciclo do `candidate`),
e FK pro `address` (Profile→Address, §4 — endereço é entidade própria).

Unicidade "nem falsos" (spec auth) = `unique` no banco + validação de formato (auth.validation) +
veracidade real no register (CPFHub p/ cpf, WhatsApp check_numbers p/ phone).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Profile(models.Model):
    """1-1 com o User. Guarda os campos de unicidade/contato exigidos pelo auth."""

    GENDER_CHOICES = (("M", "masculino"), ("F", "feminino"))

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    # NULO no funil do lead v2 (protótipo 2026-07-18): a conta nasce no passo do TELEFONE e o CPF
    # entra no passo 3 (`auth.confirm_identity`). `unique` continua valendo entre não-nulos.
    cpf = models.CharField("CPF", max_length=11, unique=True, null=True, blank=True)
    # telefone no formato canônico DDI+DDD+número (55+DDD+9+8 = 13 díg) — o mesmo que o WhatsApp/
    # notify usam (resolve_br_number). Guardamos o número resolvido (variante registrada no zap).
    phone = models.CharField("telefone", max_length=13, unique=True)
    email = models.EmailField("e-mail", unique=True, null=True, blank=True)
    gender = models.CharField(
        "gênero",
        max_length=1,
        choices=GENDER_CHOICES,
        null=True,
        blank=True,
    )
    # profiles completo (ciclo 3b): name/birth_date vêm do CPFHub; pix_key só o campo (validação
    # Asaas adiada); address = FK pra entidade própria (Profile→Address, §4), 1 endereço por profile.
    name = models.CharField("nome", max_length=200, null=True, blank=True)
    # Foto de perfil do WhatsApp (funil v2, tela 3-4): capturada em task async logo após a conta
    # nascer no check (users/roles/lead/tasks.fetch_whatsapp_avatar) — alimenta o pergaminho da
    # identidade. É ILUSTRAÇÃO, nunca prova de identidade: foto pública, definida pelo usuário no
    # zap, e a URL do CDN do WhatsApp EXPIRA — quem consome trata ausência/link morto como "sem
    # foto" (placeholder), não como erro. TextField: as URLs do pps.whatsapp.net são compridas.
    whatsapp_photo_url = models.TextField(
        "foto do WhatsApp (URL)", null=True, blank=True
    )
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    pix_key = models.CharField("chave Pix", max_length=140, null=True, blank=True)
    pix_key_type = models.CharField(
        "tipo da chave Pix", max_length=10, null=True, blank=True
    )
    # IDENTIDADE CENTRALIZADA AQUI (Victor 2026-06-16): filiação/estado civil/nacionalidade/
    # naturalidade moram SÓ no Profile. O que o OCR extrai do documento é gravado aqui — NUNCA
    # espalhado nos models de processo (candidate/enrollment). O Profile é o lugar único da pessoa.
    mother_name = models.CharField("nome da mãe", max_length=255, null=True, blank=True)
    father_name = models.CharField("nome do pai", max_length=255, null=True, blank=True)
    marital_status = models.CharField(
        "estado civil", max_length=32, null=True, blank=True
    )
    nationality = models.CharField(
        "nacionalidade", max_length=64, null=True, blank=True
    )
    birthplace = models.CharField("naturalidade", max_length=128, null=True, blank=True)
    # escolaridade — nível-PESSOA (Victor 2026-07-08): capturada no fim do wizard do candidato,
    # reusada pelo enrollment sem re-perguntar. Decide `Promoter.pre_matriculado` (sem médio completo).
    # choices espelham EducationalData.Level (users/roles/enrollment/models.py); string crua p/ evitar
    # import cruzado profiles↔roles.
    education_level = models.CharField(
        "escolaridade",
        max_length=16,
        choices=(
            ("fundamental", "Ensino Fundamental"),
            ("medio", "Ensino Médio"),
            ("superior", "Ensino Superior"),
        ),
        null=True,
        blank=True,
    )
    education_completed = models.BooleanField(
        "concluiu o nível?", null=True, blank=True
    )
    education_grade = models.PositiveSmallIntegerField(
        "última série/ano", null=True, blank=True
    )
    education_last_completed_grade = models.PositiveSmallIntegerField(
        "última série/ano concluído", null=True, blank=True
    )
    education_qualification = models.CharField(
        "última formação superior frequentada", max_length=32, null=True, blank=True
    )
    education_last_completed_qualification = models.CharField(
        "última formação superior concluída", max_length=32, null=True, blank=True
    )
    education_status = models.CharField(
        "situação da última série",
        max_length=16,
        choices=(
            ("completed", "Concluiu"),
            ("attending", "Está cursando"),
            ("stopped", "Parou antes de concluir"),
        ),
        null=True,
        blank=True,
    )
    education_year = models.PositiveSmallIntegerField(
        "ano da última frequência", null=True, blank=True
    )
    education_city = models.CharField(
        "cidade onde estudou", max_length=128, null=True, blank=True
    )
    education_school = models.CharField(
        "última escola", max_length=255, null=True, blank=True
    )
    # flag nível-PESSOA (Victor 2026-07-08): selfie reprovou 5× → não bloqueia, mas obriga encontro
    # presencial no fim do curso (coordenador tira a foto e posta como assinatura → flag cai).
    selfie_needs_meeting = models.BooleanField(
        "selfie exige encontro presencial", default=False
    )
    address = models.OneToOneField(
        "users.Address",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profile",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_profile"
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self) -> str:
        return f"profile<{self.cpf}>"
