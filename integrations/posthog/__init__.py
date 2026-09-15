"""PostHog Telemetry Integration (Server-side Event Tracking with LGPD scrubbing)."""

from integrations.posthog.client import (
    capture_event,
    is_posthog_enabled,
    track_funnel_checked,
    track_funnel_created,
    track_otp_event,
    track_payment_event,
)

__all__ = [
    "capture_event",
    "is_posthog_enabled",
    "track_funnel_checked",
    "track_funnel_created",
    "track_otp_event",
    "track_payment_event",
]
