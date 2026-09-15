"""System checks do integrations.tools.biometric — só AVISAM (Warning), NÃO travam o boot (decisão do Victor).

A biometria é apoio do funil; o caminho do dinheiro não pode quebrar por causa dela. Por isso, ao
contrário do asaas/ai (E*), aqui tudo é W* (Warning). Os checks são BARATOS: não carregam o modelo nem
disparam o download (~326MB) — isso é preguiçoso, no 1º uso real.

- `biometric.W001`: deps pesadas ausentes (insightface/onnxruntime/cv2/numpy) → face-match cai em review.
- `biometric.W002`: modelo `buffalo_l` ainda não baixado em disco (baixa no 1º uso).
- `biometric.W003`: diretório raiz do modelo não existe (será criado no 1º uso).
"""

from pathlib import Path

from django.conf import settings
from django.core.checks import Warning


def check_biometric(app_configs, **kwargs):
    warnings = []

    missing = []
    for mod in ("insightface", "onnxruntime", "cv2", "numpy"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001 — qualquer falha de import = dep indisponível
            missing.append(mod)
    if missing:
        warnings.append(
            Warning(
                f"Deps de biometria ausentes: {missing} — o face-match cai em revisão até instalar.",
                hint="uv add insightface onnxruntime opencv-python-headless numpy",
                id="biometric.W001",
            )
        )

    root = Path(settings.BIOMETRIC_MODEL_ROOT)
    model_dir = root / "models" / settings.BIOMETRIC_MODEL_NAME
    if not model_dir.exists():
        warnings.append(
            Warning(
                f"Modelo InsightFace '{settings.BIOMETRIC_MODEL_NAME}' não baixado em {model_dir}.",
                hint="Baixa sozinho no 1º uso (manage.py biometric_health) — só precisa de internet.",
                id="biometric.W002",
            )
        )
    if not root.exists():
        warnings.append(
            Warning(
                f"Diretório do modelo não existe: {root} (será criado no 1º uso).",
                hint="Confirme BIOMETRIC_MODEL_ROOT no .env se quiser um caminho fixo.",
                id="biometric.W003",
            )
        )
    return warnings
