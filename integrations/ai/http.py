"""Shared HTTP client pool for AI integrations with connection reuse and Keep-Alive.

Eliminates repetitive TCP/TLS handshake latency (100ms - 350ms per call) across
AI client requests, vision, STT, and external provider calls.
"""

from __future__ import annotations

import threading
import httpx

_client: httpx.AsyncClient | None = None
_lock = threading.Lock()


def get_ai_http_client(timeout: float = 60.0) -> httpx.AsyncClient:
    """Returns a shared, keep-alive AsyncClient instance for AI requests."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    with _lock:
        if _client is not None and not _client.is_closed:
            return _client
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=30.0,
            ),
        )
        return _client


async def close_ai_http_client() -> None:
    """Closes the shared AsyncClient instance if currently open."""
    global _client
    with _lock:
        if _client is not None:
            if not _client.is_closed:
                await _client.aclose()
            _client = None
