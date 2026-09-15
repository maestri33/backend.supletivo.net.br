"""Cliente Google Ads API para envio de conversões offline de Purchase (ClickConversion / Enhanced Conversions)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from django.conf import settings
from django.utils import timezone

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


def send_google_purchase(
    lead: Lead, checkout: Checkout, attribution: LeadAttribution | None
) -> dict[str, Any] | None:
    """Envia evento de conversão para a API do Google Ads (Offline Conversion Import)."""
    customer_id = str(
        get_setting("GOOGLE_ADS_CUSTOMER_ID", getattr(settings, "GOOGLE_ADS_CUSTOMER_ID", "")) or ""
    ).strip().replace("-", "")
    conversion_action_id = str(
        get_setting("GOOGLE_ADS_CONVERSION_ACTION_ID", getattr(settings, "GOOGLE_ADS_CONVERSION_ACTION_ID", "")) or ""
    ).strip()
    developer_token = str(
        get_setting("GOOGLE_ADS_DEVELOPER_TOKEN", getattr(settings, "GOOGLE_ADS_DEVELOPER_TOKEN", "")) or ""
    ).strip()
    access_token = str(
        get_setting("GOOGLE_ADS_ACCESS_TOKEN", getattr(settings, "GOOGLE_ADS_ACCESS_TOKEN", "")) or ""
    ).strip()

    if not customer_id or not conversion_action_id:
        logger.info(
            "analytics.google.skipped_unconfigured",
            external_id=str(lead.external_id),
            has_customer_id=bool(customer_id),
            has_action=bool(conversion_action_id),
        )
        return None

    user = getattr(lead, "user", None)
    profile = getattr(user, "profile", None) if user else None
    email = getattr(user, "email", None) or (getattr(profile, "email", None) if profile else None)
    phone = getattr(profile, "phone", None) or getattr(user, "phone", None)

    conversion_action = f"customers/{customer_id}/conversionActions/{conversion_action_id}"
    now_dt = timezone.now()
    # Google Ads espera formato "yyyy-mm-dd hh:mm:ss+|-hh:mm"
    tz_str = now_dt.strftime("%z")
    formatted_tz = f"{tz_str[:3]}:{tz_str[3:]}" if len(tz_str) == 5 else "+00:00"
    conversion_date_time = f"{now_dt.strftime('%Y-%m-%d %H:%M:%S')}{formatted_tz}"

    conversion: dict[str, Any] = {
        "conversionAction": conversion_action,
        "conversionDateTime": conversion_date_time,
        "conversionValue": float(checkout.amount),
        "currencyCode": "BRL",
        "orderId": str(lead.external_id),
    }

    gclid = attribution.gclid if attribution and attribution.gclid else None
    if gclid:
        conversion["gclid"] = gclid
    else:
        # Fallback sem gclid: Enhanced Conversions for Leads
        user_identifiers: list[dict[str, Any]] = []
        hashed_email = _hash_sha256(email)
        if hashed_email:
            user_identifiers.append({"hashedEmail": hashed_email})
        hashed_phone = _hash_phone(phone)
        if hashed_phone:
            user_identifiers.append({"hashedPhoneNumber": hashed_phone})

        if user_identifiers:
            conversion["userIdentifiers"] = user_identifiers

    payload = {
        "conversions": [conversion],
        "partialFailure": True,
    }

    url = f"https://googleads.googleapis.com/v17/customers/{customer_id}:uploadClickConversions"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "Content-Type": "application/json",
    }

    logger.info(
        "analytics.google.sending_purchase",
        external_id=str(lead.external_id),
        order_id=str(lead.external_id),
        amount=float(checkout.amount),
        has_gclid=bool(gclid),
    )

    try:
        with httpx.Client(timeout=10.0) as http_client:
            res = http_client.post(url, json=payload, headers=headers)
            body = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text

            if res.status_code >= 400:
                if res.status_code in _PERMANENT_STATUSES:
                    raise PermanentAnalyticsError(res.status_code, body)
                raise AnalyticsError(res.status_code, body)

            logger.info("analytics.google.purchase_sent", external_id=str(lead.external_id), response=body)
            return body if isinstance(body, dict) else {"response": body}
    except (AnalyticsError, PermanentAnalyticsError):
        raise
    except Exception as exc:
        raise AnalyticsError(500, str(exc), message=f"Google Ads API network error: {exc}") from exc
