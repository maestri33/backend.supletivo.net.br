"""Consentimento/contrato versionado (LGPD, lane #6).

O texto do contrato vivia hardcoded no front ("versão final a definir"); agora mora no BACKEND,
versionado + com hash SHA-256, pra provar QUAL versão o titular aceitou. A SELFIE é a assinatura:
ao enviar a selfie com sucesso, o backend grava o aceite (versão + hash + IP + user-agent + timestamp).
"""

from users.consent.contract import (
    PROMOTER_CONTRACT,
    STUDENT_CONTRACT,
    Contract,
)

__all__ = ["Contract", "STUDENT_CONTRACT", "PROMOTER_CONTRACT"]
