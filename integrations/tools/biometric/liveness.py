"""Prova de vida (liveness) — de ONDE vem o veredito.

NÃO existe mais liveness "próprio" da biometria (o antigo stub que passava sempre foi removido — ele
FINGIA fazer prova de vida e o resultado era descartado). O veredito real — "é uma pessoa REAL, não
foto-de-foto/tela/papel/documento?" — vem da IA de VISÃO em `users.roles._selfie.verify()` e é
COMBINADO (pior-veredito-vence) com o face-match em `users.roles._selfie.add_face_match()`.

Este módulo só descreve, para AUDITORIA, de onde saiu essa decisão. Quando entrar um provider
dedicado (FaceTec/Unico/CAF), a integração passa a morar aqui.
"""

from __future__ import annotations

from django.conf import settings


def liveness_source() -> dict:
    """Marcador de auditoria (gravado em `FaceVerification.liveness`): a prova de vida é decidida pela
    IA de visão (`users.roles._selfie`) e combinada no funil — a biometria NÃO gateia liveness sozinha."""
    return {
        "provider": getattr(settings, "BIOMETRIC_LIVENESS_PROVIDER", "vision"),
        "decided_by": "vision_ai",
    }
