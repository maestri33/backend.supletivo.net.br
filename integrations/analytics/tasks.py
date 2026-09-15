"""Tasks assíncronas do Django-Q para envio de conversões server-side."""

from __future__ import annotations

import structlog
from django.utils import timezone

from integrations.analytics.client import PermanentAnalyticsError
from integrations.analytics.google import send_google_purchase
from integrations.analytics.meta import send_meta_purchase
from users.roles.lead.models import Lead, LeadAttribution

logger = structlog.get_logger()


def send_purchase(lead_external_id: str) -> None:
    """Dispara conversão de Purchase para Meta CAPI e Google Ads com deduplicação/idempotência.

    Invocado pelo hook de pagamento (mark_paid) via transaction.on_commit.
    """
    lead = (
        Lead.objects.select_related("checkout", "user", "attribution", "promoter")
        .filter(external_id=lead_external_id)
        .first()
    )
    if lead is None:
        logger.warning("analytics.lead_not_found", external_id=lead_external_id)
        return

    if lead.status != Lead.Status.PAID:
        logger.info("analytics.lead_not_paid", external_id=lead_external_id, status=lead.status)
        return

    if lead.self_study:
        logger.info("analytics.skipped_self_study", external_id=lead_external_id)
        return

    checkout = getattr(lead, "checkout", None)
    if checkout is None or not checkout.amount:
        logger.warning("analytics.no_checkout_amount", external_id=lead_external_id)
        return

    # Garante linha de atribuição para registro dos timestamps anti-duplicata
    attribution, _ = LeadAttribution.objects.get_or_create(lead=lead)

    # 1. Meta CAPI Purchase
    if attribution.sent_meta is None:
        try:
            send_meta_purchase(lead, checkout, attribution)
            attribution.sent_meta = timezone.now()
            attribution.save(update_fields=["sent_meta"])
        except PermanentAnalyticsError as exc:
            logger.warning(
                "analytics.meta.dropped_permanent_error",
                external_id=lead_external_id,
                status=exc.status_code,
                body=exc.body,
            )
            attribution.sent_meta = timezone.now()
            attribution.save(update_fields=["sent_meta"])
        except Exception as exc:
            logger.error("analytics.meta.transient_failure", external_id=lead_external_id, error=str(exc))
            raise

    # 2. Google Ads Purchase
    if attribution.sent_google is None:
        try:
            send_google_purchase(lead, checkout, attribution)
            attribution.sent_google = timezone.now()
            attribution.save(update_fields=["sent_google"])
        except PermanentAnalyticsError as exc:
            logger.warning(
                "analytics.google.dropped_permanent_error",
                external_id=lead_external_id,
                status=exc.status_code,
                body=exc.body,
            )
            attribution.sent_google = timezone.now()
            attribution.save(update_fields=["sent_google"])
        except Exception as exc:
            logger.error("analytics.google.transient_failure", external_id=lead_external_id, error=str(exc))
            raise
