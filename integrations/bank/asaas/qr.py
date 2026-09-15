"""QR Code PIX da cobrança: grava o PNG (base64 do Asaas) em /media/ e devolve a URL.

O Asaas devolve `pixQrCode.encodedImage` como base64 (PNG, sem prefixo data:). Decodificamos e
gravamos em MEDIA_ROOT/qrcodes/<payment_id>.png, servido em /media/qrcodes/<payment_id>.png.
URL absoluta via EXTERNAL_URL (.env). Não precisa de lib de geração — o Asaas já manda o PNG pronto.
"""

import base64
from pathlib import Path

import structlog
from django.conf import settings

logger = structlog.get_logger()

_QR_SUBDIR = "qrcodes"


def _qr_path(payment_id: str) -> Path:
    return Path(settings.MEDIA_ROOT) / _QR_SUBDIR / f"{payment_id}.png"


def save_pix_qr_png(payment_id: str, encoded_image_b64: str) -> str:
    """Decodifica o base64 e grava o PNG. Retorna a URL pública."""
    png_bytes = base64.b64decode(encoded_image_b64, validate=True)
    fp = _qr_path(payment_id)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(png_bytes)
    logger.info("qrcode_saved", payment_id=payment_id, bytes=len(png_bytes))
    return qr_url_for(payment_id)


def qr_path_for(payment_id: str) -> str | None:
    """Caminho RELATIVO do PNG (`/media/qrcodes/<pid>.png`). None se o arquivo não existe.

    É o que a página PIX do front consome: o Next reescreve `/media/*` pro backend, então a
    imagem carrega **same-origin** — a URL absoluta (EXTERNAL_URL, outro domínio) bateria no CSP
    `img-src 'self'` do app e a `<img>` nem apareceria."""
    if not _qr_path(payment_id).exists():
        return None
    return f"{settings.MEDIA_URL}{_QR_SUBDIR}/{payment_id}.png"


def qr_url_for(payment_id: str) -> str | None:
    """URL pública do PNG (absoluta via EXTERNAL_URL). None se o arquivo não existe."""
    rel = qr_path_for(payment_id)
    if rel is None:
        return None
    base = (settings.EXTERNAL_URL or "").rstrip("/")
    return f"{base}{rel}" if base else rel
