"""Núcleo de visão: detecção + embedding + cosseno com InsightFace (ArcFace `buffalo_l`) em CPU.

PURO (sem DB): o `service.py` orquestra e persiste. Aqui só carrega o modelo, acha o rosto e mede.

- **Imports pesados PREGUIÇOSOS** (insightface/cv2 dentro das funções): o MÓDULO importa sempre, mesmo
  sem as deps instaladas → o boot e o `manage.py check` não quebram; só a operação real falha com
  `ModelUnavailable` (que o serviço converte em `review` = bloqueio seguro).
- **Modelo carregado no 1º uso** (nunca no import/boot): não espera o download (~326MB) nem a inferência.
- **Sem GPU**: `providers=["CPUExecutionProvider"]`, `ctx_id=-1`.
- **Embeddings ArcFace são L2-normalizados** (`normed_embedding`) → cosseno = produto escalar (Python puro,
  sem numpy). ⚠️ A escala do cosseno roda ~0.2–0.7 (mesma pessoa ~0.4–0.7; diferentes <0.3) — **NÃO** é a
  escala de "%" de APIs comerciais. O corte é CONFIG (`.env`) e CALIBRADO com pares reais no teste.
"""

from __future__ import annotations

import threading

import structlog
from django.conf import settings

from .exceptions import ModelUnavailable, NoFaceDetected

logger = structlog.get_logger()

_app = None
_lock = threading.Lock()


def _get_app():
    """Singleton do FaceAnalysis (carrega/baixa o modelo no 1º uso). Deps/modelo fora → ModelUnavailable."""
    global _app
    if _app is not None:
        return _app
    with _lock:
        if _app is not None:
            return _app
        try:
            from insightface.app import FaceAnalysis
        except Exception as exc:  # noqa: BLE001 — deps pesadas opcionais ausentes
            raise ModelUnavailable(
                f"deps de biometria ausentes (insightface): {exc}"
            ) from exc
        try:
            app = FaceAnalysis(
                name=settings.BIOMETRIC_MODEL_NAME,
                root=str(settings.BIOMETRIC_MODEL_ROOT),
                providers=["CPUExecutionProvider"],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception as exc:  # noqa: BLE001 — falha de download/carga do modelo
            raise ModelUnavailable(
                f"falha ao carregar o modelo InsightFace: {exc}"
            ) from exc
        _app = app
        logger.info("biometric.model_loaded", model=settings.BIOMETRIC_MODEL_NAME)
        return _app


def _largest_face(faces):
    """Maior bbox = rosto principal (ignora rostos pequenos ao fundo)."""

    def _area(f):
        x1, y1, x2, y2 = f.bbox
        return (x2 - x1) * (y2 - y1)

    return max(faces, key=_area)


def embed(image_path: str) -> tuple[list[float], dict]:
    """Detecta o maior rosto e devolve (embedding 512-d, meta). Sem rosto/ilegível → NoFaceDetected.

    Deps ausentes → ModelUnavailable (o serviço trata como review)."""
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001 — opencv ausente
        raise ModelUnavailable(f"deps de biometria ausentes (opencv): {exc}") from exc

    app = _get_app()
    img = cv2.imread(image_path)
    if img is None:
        raise NoFaceDetected(f"imagem ilegível: {image_path}")
    faces = app.get(img)
    if not faces:
        raise NoFaceDetected("nenhum rosto detectado na imagem")
    face = _largest_face(faces)
    emb = [float(x) for x in face.normed_embedding]
    meta = {
        "det_score": float(face.det_score),
        "bbox": [float(v) for v in face.bbox],
        "faces": len(faces),
        "model": settings.BIOMETRIC_MODEL_NAME,
    }
    return emb, meta


def face_crop_bytes(image_path: str) -> bytes | None:
    """Best-effort: recorta o MAIOR rosto e devolve JPEG bytes (None se sem rosto/deps/erro).

    Usado só para AUDITORIA (pedido do Victor 2026-06-21): guardar o rosto que a IA viu, pra o time
    conferir depois se ela não está "delirando". Nunca levanta — falha vira None e o chamador segue."""
    try:
        import cv2

        app = _get_app()
        img = cv2.imread(image_path)
        if img is None:
            return None
        faces = app.get(img)
        if not faces:
            return None
        f = _largest_face(faces)
        h, w = img.shape[:2]
        x1, y1, x2, y2 = (int(max(0.0, v)) for v in f.bbox)
        x2, y2 = min(w, x2), min(h, y2)
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        ok, buf = cv2.imencode(".jpg", crop)
        return buf.tobytes() if ok else None
    except Exception:  # noqa: BLE001 — auditoria é best-effort; nunca quebra o fluxo
        return None


def cosine(a, b) -> float:
    """Cosseno entre dois embeddings (listas de float). Python puro — sem numpy (os vetores já são L2)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(dot / (na * nb))
