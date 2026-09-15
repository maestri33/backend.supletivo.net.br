"""Cliente de armazenamento Cloudflare R2 (S3-compatible, Zero Egress Fees).

Utiliza httpx, hashlib e hmac nativos do Python para assinar requisições com
AWS SigV4 sem a dependência pesada de boto3/botocore.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
from urllib.parse import quote

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    return _sign(k_service, "aws4_request")


def is_r2_configured() -> bool:
    """Retorna True se as credenciais e bucket do Cloudflare R2 estiverem habilitados e preenchidos."""
    return bool(
        getattr(settings, "R2_ENABLED", False)
        and getattr(settings, "R2_ACCOUNT_ID", "")
        and getattr(settings, "R2_ACCESS_KEY_ID", "")
        and getattr(settings, "R2_SECRET_ACCESS_KEY", "")
        and getattr(settings, "R2_BUCKET_NAME", "")
    )


def get_r2_public_url(key: str) -> str:
    """Devolve a URL pública de um recurso no Cloudflare R2."""
    public_base = getattr(settings, "R2_PUBLIC_URL", "https://media.supletivo.net.br").rstrip("/")
    clean_key = key.lstrip("/")
    return f"{public_base}/{clean_key}"


def upload_to_r2(
    content: bytes,
    key: str,
    content_type: str = "application/octet-stream",
    timeout: float = 15.0,
) -> str | None:
    """Faz upload de bytes diretamente para o Cloudflare R2.
    
    Retorna a URL pública em caso de sucesso ou None caso não esteja configurado ou falhe.
    """
    if not is_r2_configured():
        return None

    account_id = settings.R2_ACCOUNT_ID
    access_key = settings.R2_ACCESS_KEY_ID
    secret_key = settings.R2_SECRET_ACCESS_KEY
    bucket_name = settings.R2_BUCKET_NAME
    region = "auto"
    service = "s3"

    host = f"{account_id}.r2.cloudflarestorage.com"
    clean_key = key.lstrip("/")
    canonical_uri = f"/{bucket_name}/{quote(clean_key)}"

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(content).hexdigest()

    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_request = (
        f"PUT\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"{algorithm}\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    signing_key = _get_signature_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Content-Type": content_type,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": authorization_header,
    }

    url = f"https://{host}{canonical_uri}"
    try:
        resp = httpx.put(url, content=content, headers=headers, timeout=timeout)
        if resp.status_code in (200, 201):
            public_url = get_r2_public_url(clean_key)
            logger.info("r2.uploaded", key=clean_key, url=public_url, status=resp.status_code)
            return public_url
        logger.warning(
            "r2.upload_rejected",
            status=resp.status_code,
            body=resp.text[:200],
            key=clean_key,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("r2.upload_failed", key=clean_key, error=str(exc)[:160])
        return None


def delete_from_r2(key: str, timeout: float = 10.0) -> bool:
    """Remove um arquivo do Cloudflare R2 (ex: descarte de documento anterior ao re-upload)."""
    if not is_r2_configured():
        return False

    account_id = settings.R2_ACCOUNT_ID
    access_key = settings.R2_ACCESS_KEY_ID
    secret_key = settings.R2_SECRET_ACCESS_KEY
    bucket_name = settings.R2_BUCKET_NAME
    region = "auto"
    service = "s3"

    host = f"{account_id}.r2.cloudflarestorage.com"
    clean_key = key.lstrip("/")
    canonical_uri = f"/{bucket_name}/{quote(clean_key)}"

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(b"").hexdigest()

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = (
        f"DELETE\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"{algorithm}\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    signing_key = _get_signature_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": authorization_header,
    }

    url = f"https://{host}{canonical_uri}"
    try:
        resp = httpx.delete(url, headers=headers, timeout=timeout)
        if resp.status_code in (200, 204):
            logger.info("r2.deleted", key=clean_key, status=resp.status_code)
            return True
        logger.warning("r2.delete_rejected", key=clean_key, status=resp.status_code)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("r2.delete_failed", key=clean_key, error=str(exc)[:160])
        return False
