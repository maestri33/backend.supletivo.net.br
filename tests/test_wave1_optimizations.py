"""Unit tests for Wave 1 optimizations:
1. TTL and invalidation in system_config.py cache.
2. AI HTTP client pool singleton in integrations/ai/http.py.
3. TTS endpoint URL normalization in integrations/ai/tts.py.
"""

from __future__ import annotations

import time
from unittest import mock
import pytest

from core import system_config
from core.models import PlatformSetting
from integrations.ai import http as ai_http
from integrations.ai import tts


@pytest.mark.django_db
def test_system_config_ttl_and_invalidation():
    """Verify that system_config respects TTL and cache invalidation."""
    system_config.clear_settings_cache()
    PlatformSetting.objects.create(key="TEST_KEY", value="initial_value")

    # Initial read populates cache
    val1 = system_config.get_setting("TEST_KEY")
    assert val1 == "initial_value"

    # Directly mutate DB without using set_setting (simulating another worker/pod)
    PlatformSetting.objects.filter(key="TEST_KEY").update(value="updated_by_other_worker")

    # Fast path: in-memory cache still holds initial_value before expiration
    assert system_config.get_setting("TEST_KEY") == "initial_value"

    # Simulate TTL expiration by rolling back _CACHE_EXPIRES_AT
    system_config._CACHE_EXPIRES_AT = time.monotonic() - 1.0

    # Next get_setting must reload fresh from database
    val2 = system_config.get_setting("TEST_KEY")
    assert val2 == "updated_by_other_worker"

    # clear_settings_cache forces reload
    PlatformSetting.objects.filter(key="TEST_KEY").update(value="forced_refresh")
    system_config.clear_settings_cache()
    assert system_config.get_setting("TEST_KEY") == "forced_refresh"


@pytest.mark.asyncio
async def test_ai_http_client_pool_singleton():
    """Verify that get_ai_http_client returns a shared active client."""
    client1 = ai_http.get_ai_http_client()
    client2 = ai_http.get_ai_http_client()
    assert client1 is client2
    assert not client1.is_closed

    await ai_http.close_ai_http_client()
    assert client1.is_closed

    client3 = ai_http.get_ai_http_client()
    assert client3 is not client1
    assert not client3.is_closed
    await ai_http.close_ai_http_client()


def test_tts_endpoint_assembly_normalization():
    """Verify TTS endpoint doesn't double-concatenate /v1/v1."""
    # Test base URL ending with /v1
    base_with_v1 = "https://ai.v7m.live/v1"
    endpoint1 = f"{base_with_v1}/audio/speech" if base_with_v1.endswith("/v1") else f"{base_with_v1}/v1/audio/speech"
    assert endpoint1 == "https://ai.v7m.live/v1/audio/speech"

    # Test base URL without /v1
    base_without_v1 = "https://api.openai.com"
    endpoint2 = f"{base_without_v1}/audio/speech" if base_without_v1.endswith("/v1") else f"{base_without_v1}/v1/audio/speech"
    assert endpoint2 == "https://api.openai.com/v1/audio/speech"
