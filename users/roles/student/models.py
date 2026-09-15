"""Models do `student`/`veteran` (§4 item 9) — porte do legado (`~/coders/backend/student`).

`Student` é a raiz (1-1 com o User), criada na liberação da matrícula. Carrega o HUB herdado do
enrollment (origem da comissão do coordenador) e os dados da plataforma de estudo (campos
estruturados — decisão do Victor 2026-06-04). Os documentos do aluno (`StudentDocument`) carregam o
estado da validação por IA; a prova (`StudentExam`) o coordenador corrige; o diploma (`StudentDiploma`)
o coordenador emite e o aluno retira (foto); a pendência (`StudentPendency`) é o «conferir» do spec
(documento OU taxa — decisão do Victor 2026-06-04).

Tudo sob o app_label `users` (sub-pacote, 1 migration set — igual enrollment/candidate; CONVENTION §2).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel


class Student(ExternalIdModel):
    """O aluno (1-1 com o User). Nasce na liberação da matrícula, em `AWAITING_DOCUMENTS`."""

    class Status(models.TextChoices):
        AWAITING_DOCUMENTS = "awaiting_documents", "aguardando documentos"
        DOCUMENTS_UNDER_REVIEW = "documents_under_review", "documentos em análise (IA)"
        EXAM_RELEASED = "exam_released", "liberado para agendar a prova"
        EXAM_SCHEDULED = "exam_scheduled", "prova agendada"
        EXAM_FAILED = "exam_failed", "reprovado na prova (refazer)"
        AWAITING_DOCUMENTATION_DISPATCH = (
            "awaiting_documentation_dispatch",
            "aguardando envio de documentação",
        )
        PENDING = "pending", "com pendência"
        AWAITING_DIPLOMA_ISSUANCE = (
            "awaiting_diploma_issuance",
            "aguardando emissão do diploma",
        )
        AWAITING_PICKUP = "awaiting_pickup", "aguardando retirada"
        VETERAN = "veteran", "veterano"

    # tipo sanguíneo — spec "obrigatório especificar" (valor textual; a FOTO é um StudentDocument).
    class BloodType(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student",
    )
    # hub herdado do enrollment — quem ganha a comissão na formatura é o coordenador deste hub.
    hub = models.ForeignKey(
        "hub.Hub",
        on_delete=models.PROTECT,
        related_name="students",
    )
    # auto-matrícula de promotor (herdado do enrollment): coordenador NÃO recebe comissão na formatura.
    self_study = models.BooleanField(default=False)
    # bolsista (Victor 2026-07-08, herdado do enrollment): teste final exige ≥10 leads pagos do
    # promotor-que-ele-foi, além de docs+sangue (gate em `_maybe_release_exam`).
    bolsista = models.BooleanField(default=False)
    status = models.CharField(
        max_length=40,
        choices=Status.choices,
        default=Status.AWAITING_DOCUMENTS,
        db_index=True,
    )
    # dados da plataforma de estudo (campos estruturados — Victor 2026-06-04). O coordenador insere
    # na liberação; o aluno acessa depois. `platform_password` é credencial de plataforma EXTERNA
    # (login compartilhado que o coordenador fornece) — não é senha de usuário nosso.
    platform_url = models.URLField(max_length=500, null=True, blank=True)
    platform_login = models.CharField(max_length=255, null=True, blank=True)
    platform_password = models.CharField(max_length=255, null=True, blank=True)
    platform_notes = models.TextField(null=True, blank=True)
    # tipo sanguíneo (valor); a foto correspondente é um StudentDocument(BLOOD_TYPE).
    blood_type = models.CharField(
        max_length=3, choices=BloodType.choices, null=True, blank=True
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_student"
        verbose_name = "aluno"
        verbose_name_plural = "alunos"
        constraints = [
            # login da plataforma é ÚNICO por matrícula (Victor 2026-06-23). Parcial: só vale pra
            # login preenchido — `__gt=""` exclui null e string vazia.
            models.UniqueConstraint(
                fields=["platform_login"],
                condition=models.Q(platform_login__gt=""),
                name="uniq_student_platform_login",
            ),
        ]

    def __str__(self) -> str:
        return f"student<{self.external_id}:{self.status}>"


class StudentDocument(ExternalIdModel):
    """Documento que o aluno envia + estado da validação por IA (assíncrona). 1 por (aluno, tipo)."""

    class Type(models.TextChoices):
        MILITARY = "military_service", "serviço militar (só homens)"
        CERTIFICATE = "certificate", "certificado do último ano"
        TRANSCRIPT = "transcript", "histórico escolar"
        BLOOD_TYPE = "blood_type", "tipo sanguíneo (foto)"
        ADDRESS_PROOF = "address_proof", "comprovante de endereço (foto)"
        ID_CARD = "id_card", "documento pessoal / RG (foto)"
        BIRTH_CERTIFICATE = "birth_certificate", "certidão"

    class Validation(models.TextChoices):
        PENDING = "pending", "aguardando IA"
        APPROVED = "approved", "aprovado"  # IA ou coordenador
        REJECTED = "rejected", "reprovado"  # IA ou coordenador → dono refaz
        REVIEW = "review", "em revisão (coordenador decide)"  # IA falhou/em dúvida

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="documents"
    )
    doc_type = models.CharField(max_length=40, choices=Type.choices, db_index=True)
    # foto: path relativo no DB (arquivo em media/student/<student_ext>/<doc_type>.<ext>).
    photo = models.CharField("foto", max_length=500, null=True, blank=True)
    validation_status = models.CharField(
        max_length=20,
        choices=Validation.choices,
        default=Validation.PENDING,
        db_index=True,
    )
    # resultado bruto da IA (descrição/motivo) — auditoria.
    validation_result = models.JSONField(null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_student_document"
        verbose_name = "documento do aluno"
        verbose_name_plural = "documentos do aluno"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "doc_type"], name="uniq_student_doc_type"
            )
        ]

    def __str__(self) -> str:
        return f"student_doc<{self.doc_type}:{self.validation_status}>"


class StudentExam(ExternalIdModel):
    """Prova: o aluno agenda (matéria + data); o coordenador corrige. Reprovou → nova tentativa."""

    class Result(models.TextChoices):
        PASSED = "passed", "aprovado"
        FAILED = "failed", "reprovado"

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="exams")
    subject = models.CharField("matéria", max_length=120)
    scheduled_at = models.DateTimeField("agendada para")
    attempt_number = models.PositiveIntegerField("tentativa", default=1)
    result = models.CharField(
        max_length=20, choices=Result.choices, null=True, blank=True
    )
    # coordenador que corrigiu (FK real — §4; é Django/monólito).
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exams_corrected",
    )
    corrected_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField("observações", max_length=500, null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_student_exam"
        verbose_name = "prova do aluno"
        verbose_name_plural = "provas do aluno"

    def __str__(self) -> str:
        return f"student_exam<{self.subject}:t{self.attempt_number}:{self.result}>"


class StudentDiploma(ExternalIdModel):
    """Diploma: o coordenador emite (sobe o PDF do diploma + histórico) e registra a retirada (foto do
    aluno recebendo). 1 por aluno. TODO o fluxo é do coordenador (Victor 2026-06-29): o aluno não posta
    nada — só é notificado a comparecer ao polo."""

    student = models.OneToOneField(
        Student, on_delete=models.CASCADE, related_name="diploma"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diplomas_issued",
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    # arquivos que o coordenador sobe na emissão (path relativo; PDF ou imagem). media/diploma/.
    diploma_file = models.CharField(max_length=500, null=True, blank=True)
    transcript_file = models.CharField(max_length=500, null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    # foto do aluno recebendo o diploma — o COORDENADOR posta (media/diploma/<token>.<ext>).
    pickup_photo = models.CharField(max_length=500, null=True, blank=True)
    # idempotência: marca quando a comissão do coordenador foi disparada (não credita 2×).
    commission_triggered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_student_diploma"
        verbose_name = "diploma"
        verbose_name_plural = "diplomas"

    def __str__(self) -> str:
        return f"student_diploma<{self.student_id}>"


class StudentPendency(ExternalIdModel):
    """O «conferir» do spec (Victor: ambos) — o coordenador lança pendência de DOCUMENTO ou de TAXA.

    DOCUMENTO: falta/reprovou um documento que a escola precisa despachar. TAXA: pendência financeira
    (`amount_cents`/`fee_request` opcionais). ⚠️ taxa NÃO move dinheiro aqui — é registro; pagar de
    verdade é pelo motor `fees` com OK do Victor (Portão 3). O aluno vê a pendência (GET) e resolve.
    """

    class Kind(models.TextChoices):
        DOCUMENT = "document", "documentação"
        FEE = "fee", "taxa/comissão"

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="pendencies"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.CharField(max_length=500)
    amount_cents = models.PositiveIntegerField(null=True, blank=True)  # só kind=fee
    # FK real pro PaymentRequest do motor fees (era CharField solto). SET_NULL preserva a pendência.
    fee_request = models.ForeignKey(
        "finance.PaymentRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pendencies_opened",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_student_pendency"
        verbose_name = "pendência do aluno"
        verbose_name_plural = "pendências do aluno"

    def __str__(self) -> str:
        return f"student_pendency<{self.kind}:{'open' if self.resolved_at is None else 'resolved'}>"
