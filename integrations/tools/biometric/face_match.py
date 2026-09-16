"""Núcleo de visão e biometria: detecção + embedding + cosseno (ArcFace `buffalo_l`).

PURO (sem DB): o `service.py` orquestra e persiste.
- Desacoplado: consome o microsserviço isolado no Proxmox VE via HTTP (`BIOMETRIC_SERVICE_URL`),
  zerando o consumo de RAM no Django e eliminando dependências pesadas de C++ (OpenCV/InsightFace).
- Fallback in-process preguiçoso se o serviço não estiver configurado e o módulo local existir.
- Embeddings ArcFace são L2-normalizados (`normed_embedding`) -> cosseno = produto escalar (Python puro).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import threading

import httpx
import structlog
from django.conf import settings

from .exceptions import ModelUnavailable, NoFaceDetected

logger = structlog.get_logger()

_app = None
_lock = threading.Lock()
_http_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_http_client(timeout: float = 15.0) -> httpx.Client:
    """Singleton thread-safe do cliente HTTP para reuso de conexões TCP (Keep-Alive)."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        return _http_client
    with _client_lock:
        if _http_client is not None and not _http_client.is_closed:
            return _http_client
        _http_client = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        return _http_client


def _prepare_image_bytes(data: bytes, max_dim: int = 1600) -> bytes:
    """Pré-otimiza a imagem antes de enviar via rede: redimensiona se maior que max_dim mantendo EXIF."""
    try:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if max(w, h) > max_dim:
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                out = BytesIO()
                im.convert("RGB").save(out, format="JPEG", quality=90)
                return out.getvalue()
    except Exception:
        pass
    return data


def _get_local_app():
    """Singleton opcional do FaceAnalysis local (usado apenas se não houver BIOMETRIC_SERVICE_URL)."""
    global _app
    if _app is not None:
        return _app
    with _lock:
        if _app is not None:
            return _app
        try:
            from insightface.app import FaceAnalysis
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(
                f"deps de biometria ausentes (insightface/opencv): {exc}"
            ) from exc
        try:
            app = FaceAnalysis(
                name=settings.BIOMETRIC_MODEL_NAME,
                root=str(settings.BIOMETRIC_MODEL_ROOT),
                providers=["CPUExecutionProvider"],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(
                f"falha ao carregar o modelo InsightFace local: {exc}"
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
    """Detecta o maior rosto e devolve (embedding 512-d, meta). Sem rosto/ilegível -> NoFaceDetected.

    Se BIOMETRIC_SERVICE_URL estiver configurado, consome o microsserviço HTTP remoto.
    Caso contrário, tenta o fallback local se insightface estiver instalado.
    """
    p = Path(image_path)
    if not p.exists():
        raise NoFaceDetected(f"imagem ilegível ou não encontrada: {image_path}")

    service_url = getattr(settings, "BIOMETRIC_SERVICE_URL", "").rstrip("/")
    if service_url:
        try:
            image_data = _prepare_image_bytes(p.read_bytes())
            timeout = getattr(settings, "BIOMETRIC_TIMEOUT", 15.0)
            client = _get_http_client(timeout=timeout)
            files = {"file": (p.name, image_data, "image/jpeg")}
            resp = client.post(f"{service_url}/embed", files=files)

            if resp.status_code == 404 or resp.status_code == 422:
                detail = resp.json().get("detail", "nenhum rosto detectado")
                raise NoFaceDetected(detail)
            if resp.status_code >= 400:
                raise ModelUnavailable(
                    f"serviço biométrico HTTP {resp.status_code}: {resp.text[:200]}"
                )

            data = resp.json()
            emb = [float(x) for x in data["embedding"]]
            meta = data.get("meta", {
                "det_score": float(data.get("det_score", 1.0)),
                "bbox": [float(v) for v in data.get("bbox", [0, 0, 0, 0])],
                "faces": data.get("faces", 1),
                "model": settings.BIOMETRIC_MODEL_NAME,
            })
            return emb, meta
        except (NoFaceDetected, ModelUnavailable):
            raise
        except Exception as exc:
            raise ModelUnavailable(
                f"falha de comunicação com serviço biométrico ({service_url}): {exc}"
            ) from exc

    # Fallback local se insightface/opencv estiverem presentes
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(
            f"serviço biométrico não configurado e deps locais ausentes: {exc}"
        ) from exc

    app = _get_local_app()
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


def face_crop_bytes(image_path: str, bbox: list[float] | None = None) -> bytes | None:
    """Best-effort: recorta o rosto e devolve JPEG bytes usando Pillow (sem OpenCV)."""
    try:
        from PIL import Image

        p = Path(image_path)
        if not p.exists():
            return None

        with Image.open(p) as img:
            img = img.convert("RGB")
            w, h = img.size
            if bbox and len(bbox) == 4:
                x1, y1, x2, y2 = (int(max(0.0, v)) for v in bbox)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 > x1 and y2 > y1:
                    crop = img.crop((x1, y1, x2, y2))
                    buf = BytesIO()
                    crop.save(buf, format="JPEG", quality=90)
                    return buf.getvalue()
        return None
    except Exception:  # noqa: BLE001
        return None


def cosine(a, b) -> float:
    """Cosseno entre dois embeddings (listas de float). Python puro — sem numpy (os vetores já são L2)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(dot / (na * nb))

