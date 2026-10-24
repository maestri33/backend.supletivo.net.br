"""Receipt URL validation utilities for payment gateways."""

from urllib.parse import urlsplit


def safe_receipt_url(value: str | None) -> str | None:
    """Receipt links may only navigate to a known gateway over HTTPS."""
    if not isinstance(value, str) or len(value) > 500:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        trusted = ("infinitepay.io", "infinitepay.com.br", "asaas.com", "asaas.com.br")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        if not any(host == domain or host.endswith("." + domain) for domain in trusted):
            return None
    except ValueError:
        return None
    return value
