"""Cliente Meta Conversions API (CAPI) para envio de eventos server-side de Purchase."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from django.conf import settings

from core.system_config import get_setting
from integrations.analytics.client import (
    _PERMANENT_STATUSES,
    AnalyticsError,
    PermanentAnalyticsError,
)

if TYPE_CHECKING:
    from users.roles.lead.models import Checkout, Lead, LeadAttribution

logger = structlog.get_logger()


def _hash_sha256(val: str | None) -> str | None:
    if not val:
        return None
    cleaned = val.strip().lower()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _hash_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return None
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = f"55{digits}"
    return hashlib.sha256(digits.encode("utf-8")).hexdigest()


def send_meta_purchase(
    lead: Lead, checkout: Checkout, attribution: LeadAttribution | None
) -> dict[str, Any] | None:
    """Envia evento de Purchase via Meta Conversions API (CAPI)."""
    pixel_id = str(
        get_setting("META_PIXEL_ID", getattr(settings, "META_PIXEL_ID", "")) or ""
    ).strip()
    capi_token = str(
        get_setting("META_CAPI_TOKEN", getattr(settings, "META_CAPI_TOKEN", "")) or ""
    ).strip()

    if not pixel_id or not capi_token:
        logger.info(
            "analytics.meta.skipped_unconfigured",
            external_id=str(lead.external_id),
            has_pixel=bool(pixel_id),
            has_token=bool(capi_token),
        )
        return None

    user = getattr(lead, "user", None)
    profile = getattr(user, "profile", None) if user else None

    email = getattr(user, "email", None) or (getattr(profile, "email", None) if profile else None)
    phone = getattr(profile, "phone", None) or getattr(user, "phone", None)

    user_data: dict[str, Any] = {}
    hashed_email = _hash_sha256(email)
    if hashed_email:
        user_data["em"] = [hashed_email]

    hashed_phone = _hash_phone(phone)
    if hashed_phone:
        user_data["ph"] = [hashed_phone]

    if attribution:
        if attribution.fbp:
            user_data["fbp"] = attribution.fbp
        if attribution.fbc:
            user_data["fbc"] = attribution.fbc
        elif attribution.fbclid:
            user_data["fbc"] = f"fb.1.{int(time.time())}.{attribution.fbclid}"
        if attribution.client_ip:
            user_data["client_ip_address"] = attribution.client_ip
        if attribution.user_agent:
            user_data["client_user_agent"] = attribution.user_agent

    event_payload: dict[str, Any] = {
        "event_name": "Purchase",
        "event_time": int(time.time()),
        "action_source": "website",
        "event_id": str(lead.external_id),
        "event_source_url": (attribution.landing_url if attribution and attribution.landing_url else "https://supletivo.net.br"),
        "user_data": user_data,
        "custom_data": {
            "value": float(checkout.amount),
            "currency": "BRL",
        },
    }

    test_event_code = str(
        get_setting("META_TEST_EVENT_CODE", getattr(settings, "META_TEST_EVENT_CODE", "")) or ""
    ).strip()
    payload: dict[str, Any] = {"data": [event_payload]}
    if test_event_code:
        payload["test_event_code"] = test_event_code

    url = f"https://graph.facebook.com/v19.0/{pixel_id}/events"
    headers = {
        "Authorization": f"Bearer {capi_token}",
        "Content-Type": "application/json",
    }

    logger.info(
        "analytics.meta.sending_purchase",
        external_id=str(lead.external_id),
        event_id=str(lead.external_id),
        amount=float(checkout.amount),
    )

    try:
        with httpx.Client(timeout=10.0) as http_client:
            res = http_client.post(url, json=payload, headers=headers)
            body = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text

            if res.status_code >= 400:
                if res.status_code in _PERMANENT_STATUSES:
                    raise PermanentAnalyticsError(res.status_code, body)
                raise AnalyticsError(res.status_code, body)

            logger.info("analytics.meta.purchase_sent", external_id=str(lead.external_id), response=body)
            return body if isinstance(body, dict) else {"response": body}
    except (AnalyticsError, PermanentAnalyticsError):
        raise
    except Exception as exc:
        raise AnalyticsError(500, str(exc), message=f"Meta CAPI network error: {exc}") from exc
