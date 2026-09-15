"""
Agentic Commerce Protocol (ACP) Discovery Document (RFC v2026-01-30).

Implements:
- /.well-known/acp.json per https://agenticcommerce.dev
Allows autonomous AI agents to discover commerce APIs, supported transports,
protocol versions, and capabilities before initiating checkout sessions.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

ACP_PROTOCOL_NAME = "acp"
ACP_PROTOCOL_VERSION = "2026-01-30"
ACP_SUPPORTED_VERSIONS = ["2025-09-29", "2026-01-30"]
ACP_DOCUMENTATION_URL = "https://agenticcommerce.dev"
ACP_DEFAULT_TRANSPORTS = ["rest"]
ACP_DEFAULT_SERVICES = ["checkout", "orders"]


def _get_base_url(request: HttpRequest) -> str:
    """Resolve the canonical base URL from request or forwarded headers."""
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    return request.build_absolute_uri("/").rstrip("/")


@require_GET
def acp_discovery_view(request: HttpRequest) -> JsonResponse:
    """
    Serve /.well-known/acp.json with HTTP 200.

    Requirements:
    - protocol.name = "acp"
    - protocol.version = string (e.g. "2026-01-30")
    - api_base_url = absolute HTTP(S) URL
    - transports = non-empty array of strings
    - capabilities.services = non-empty array of strings
    """
    base_url = _get_base_url(request)

    data = {
        "protocol": {
            "name": ACP_PROTOCOL_NAME,
            "version": ACP_PROTOCOL_VERSION,
            "supported_versions": ACP_SUPPORTED_VERSIONS,
            "documentation_url": ACP_DOCUMENTATION_URL,
        },
        "api_base_url": base_url,
        "transports": ACP_DEFAULT_TRANSPORTS,
        "capabilities": {
            "services": ACP_DEFAULT_SERVICES,
        },
        "merchant": {
            "name": "Supletivo Brasil",
            "country": "BR",
            "currency": "BRL",
        },
    }

    response = JsonResponse(data, json_dumps_params={"indent": 2})
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
    response["Cache-Control"] = "public, max-age=3600"
    return response
