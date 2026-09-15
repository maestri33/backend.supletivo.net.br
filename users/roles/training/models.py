"""Training — o LMS do funil do colaborador, agora como TRAVA pós-promotor (Victor 2026-06-16).

Modelo novo: o candidato vira **promotor** quando o coordenador aprova (não há mais entrevista/Trainee).
Aí o treino vira uma **trava do painel**: enquanto o promotor tiver matéria OBRIGATÓRIA pendente, ele
ganha a role overlay `training` (blocking) e o front trava. Matérias:

- `kind` **fixa**: toda matéria fixa ativa é atribuída a TODO promotor ao ser aprovado (onboarding).
- `kind` **transitória**: o staff PUBLICA → atribui só aos promotores JÁ existentes naquele momento.
- `blocking`: obrigatória trava o painel; opcional (não-blocking) não trava.
- `ephemeral`: descartável (o staff pode deletar; não deixa peso histórico).

3 models: `Material` (a matéria + conteúdo rico) · `MaterialAssignment` (atribuição user↔matéria =
FONTE DA VERDADE da trava: pending/approved) · `Submission` (resposta → IA corrige). Sub-pacote de
`users` (app_label `users`).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel


class Material(ExternalIdModel):
    """Uma matéria do treino: conteúdo (texto/vídeo/foto/blocos) + 1 questão + 1 gabarito (a IA corrige)."""

    class Kind(models.TextChoices):
        FIXED = "fixed", "fixa (todo promotor novo recebe)"
        TRANSITORY = (
            "transitory",
            "transitória (só os promotores já existentes ao publicar)",
        )

    title = models.CharField(max_length=255)
    text_content = models.TextField(blank=True, default="")
    # conteúdo rico extra além do texto: lista de blocos {type: text|image|video|file, value, caption?}.
    # O staff preenche (URLs/paths de mídia); o front renderiza em ordem. "texto, imagem e outros" (Victor).
    content_blocks = models.JSONField(default=list, blank=True)
    question = models.TextField()
    expected_answer = models.TextField()  # gabarito (a IA compara a resposta com isto)
    video = models.CharField(max_length=255, null=True, blank=True)  # media/training/
    photo = models.CharField(max_length=255, null=True, blank=True)
    kind = models.CharField(
        max_length=12,
        choices=Kind.choices,
        default=Kind.FIXED,
        db_index=True,
    )
    blocking = models.BooleanField(
        default=True, db_index=True
    )  # obrigatória = trava o painel até aprovar
    ephemeral = models.BooleanField(default=False)  # descartável (staff pode deletar)
    order = models.PositiveIntegerField(default=0, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_training_material"
        verbose_name = "matéria do treino"
        verbose_name_plural = "matérias do treino"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"material<{self.external_id}:{self.title}>"


class MaterialAssignment(ExternalIdModel):
    """Atribuição de uma matéria a um colaborador — FONTE DA VERDADE da trava do treino.

    Criada quando: (a) o promotor é aprovado (todas as matérias FIXAS ativas) ou (b) o staff PUBLICA
    uma matéria transitória (todos os promotores existentes). `pending` enquanto não aprovada; vira
    `approved` quando uma `Submission` é aprovada OU o coordenador aprova a matéria em aberto. O
    promotor está TRAVADO sse existir alguma assignment `pending` de matéria `blocking` ativa."""

    class Status(models.TextChoices):
        PENDING = "pending", "pendente"
        APPROVED = "approved", "aprovada"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="material_assignments",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    # quando o coordenador aprova a matéria em aberto (sem submissão), fica registrado quem decidiu.
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_training_assignment"
        verbose_name = "atribuição de matéria"
        verbose_name_plural = "atribuições de matéria"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "material"], name="uniq_material_per_user"
            )
        ]

    def __str__(self) -> str:
        return f"assignment<{self.external_id}:{self.status}>"


class Submission(ExternalIdModel):
    """Uma resposta a uma matéria, corrigida pela IA (nota 0-10 + justificativa)."""

    class Status(models.TextChoices):
        PENDING = "pending", "corrigindo"
        APPROVED = "approved", "aprovada"
        REJECTED = "rejected", "reprovada"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    answer = (
        models.TextField()
    )  # texto direto OU transcrição do áudio (preenchida pela task)
    # Resposta em áudio (opcional): path em media/training/audio/. answer nasce "" e a task de
    # correção transcreve (ai.transcribe) antes de corrigir.
    audio = models.CharField(max_length=255, null=True, blank=True)
    grade = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )  # 0-10
    justification = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_training_submission"
        verbose_name = "submissão do treino"
        verbose_name_plural = "submissões do treino"

    def __str__(self) -> str:
        return f"submission<{self.external_id}:{self.status}>"
