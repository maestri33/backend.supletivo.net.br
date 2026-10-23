"""A cold async caller must honor the protected production credential override."""
import asyncio

import pytest

from core.system_config import clear_settings_cache, set_setting
from integrations.bank.asaas.client import get_client

pytestmark = pytest.mark.django_db(transaction=True)


def test_async_client_uses_protected_key_after_a_cold_start(settings):
    settings.ASAAS_API_KEY = "old-environment-key"
    expected = "offline-new-protected-key"
    set_setting("ASAAS_API_KEY", expected, is_secret=True)
    clear_settings_cache()

    async def read_header():
        async with get_client() as client:
            return client._client.headers["access_token"]
    try:
        assert asyncio.run(read_header()) == expected
    finally:
        clear_settings_cache()
