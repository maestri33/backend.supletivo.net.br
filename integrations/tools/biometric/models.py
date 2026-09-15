"""Models do integrations.tools.biometric — biometria persistente do perfil + auditoria das comparações.

Reframe do Victor (2026-06-05): a biometria não é "compara e descarta". O rosto do DOCUMENTO vira um
template SALVO, ligado ao perfil; a selfie compara com ele e TAMBÉM é salva ("expandir a biometria").

- `FaceBiometric` = um template (embedding) por captura (documento OU selfie), ligado ao `User` — a
  galeria biométrica que cresce.
- `FaceVerification` = o EVENTO de comparação (auditoria): score/threshold/veredito + de onde veio.

Ambos herdam `core.models.ExternalIdModel` (o único external_id de borda — CONVENTION §4). Nada é
descartado: mesmo erro/review grava linha (rastreabilidade, pedido do Victor).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel


class FaceBiometric(ExternalIdModel):
    """Template biométrico salvo de uma captura (documento ou selfie), ligado ao usuário."""

    class Source(models.TextChoices):
        DOCUMENT = "document", "documento"
        SELFIE = "selfie", "selfie"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="face_biometrics",
    )
    source = models.CharField(max_length=16, choices=Source.choices, db_index=True)
    image_path = models.CharField(max_length=500)
    # vetor 512-d (o template). JSONField serve em SQLite (dev) e PostgreSQL (prod).
    embedding = models.JSONField(default=list)
    det_score = models.FloatField(
        null=True, blank=True
    )  # confiança da detecção do rosto
    provider = models.CharField(max_length=32, default="insightface")
    metadata = models.JSONField(
        default=dict, blank=True
    )  # bbox/modelo/erro — nada descartado
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "source", "-created_at"])]

    def __str__(self):
        return f"{self.source} de user#{self.user_id} ({self.provider})"


class FaceVerification(ExternalIdModel):
    """Evento de comparação selfie × documento (auditoria persistente de TODA validação facial)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="face_verifications",
    )
    caller = models.CharField(
        max_length=64, db_index=True
    )  # ex.: candidate.selfie / enrollment.selfie
    reference = models.ForeignKey(
        FaceBiometric,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )  # o template do DOCUMENTO
    probe = models.ForeignKey(
        FaceBiometric,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )  # o template da SELFIE
    score = models.FloatField(null=True, blank=True)  # cosseno (null se não comparou)
    threshold = models.FloatField()  # snapshot do BIOMETRIC_MATCH_THRESHOLD vigente
    approved = models.BooleanField(default=False)  # score >= match
    status = models.CharField(
        max_length=16, db_index=True
    )  # approved | rejected | review
    provider = models.CharField(max_length=32, default="insightface")
    liveness = models.JSONField(default=dict, blank=True)  # {passed, provider}
    metadata = models.JSONField(
        default=dict, blank=True
    )  # evidência (det_score/bbox/erro)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.status} score={self.score} ({self.caller})"
