"""Erros do integrations.tools.biometric (uma raiz + 2 específicos — padrão XxxError do projeto)."""

from __future__ import annotations


class BiometricError(Exception):
    """Erro de borda da biometria facial (raiz)."""


class NoFaceDetected(BiometricError):
    """Nenhum rosto detectável na imagem (documento ruim, selfie sem rosto, imagem ilegível)."""


class ModelUnavailable(BiometricError):
    """O modelo InsightFace não está disponível (deps ausentes ou falha ao carregar)."""
