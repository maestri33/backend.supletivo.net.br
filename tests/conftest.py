# ponytail: fixtures mínimos — db + client. SQLite em memória para testes.
import os
import shutil
import tempfile
from pathlib import Path

# Força SQLite ANTES do Django ler settings (sobrescreve o .env).
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Isola MEDIA_ROOT e STATIC_ROOT antes do Django ler settings para não poluir o repositório
# e evitar warnings do WhiteNoiseMiddleware sobre diretório ausente.
_temp_media_dir = tempfile.mkdtemp(prefix="test_media_")
_temp_static_dir = tempfile.mkdtemp(prefix="test_static_")
os.environ["MEDIA_ROOT"] = _temp_media_dir
os.environ["STATIC_ROOT"] = _temp_static_dir

import pytest
from django.test import Client


def pytest_sessionfinish(session, exitstatus):
    """Limpeza garantida dos diretórios temporários criados para a sessão de testes."""
    shutil.rmtree(_temp_media_dir, ignore_errors=True)
    shutil.rmtree(_temp_static_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def test_settings():
    from django.conf import settings

    settings.TEST_MODE = True
    settings.APP_ENV = "test"
    settings.BOT_SERVICE_SECRET = "test_bot_secret"
    settings.BOT_SERVICE_HEADER = "x-bot-service-token"
    settings.MEDIA_ROOT = Path(_temp_media_dir)
    settings.STATIC_ROOT = Path(_temp_static_dir)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def bot_headers():
    return {"HTTP_X_BOT_SERVICE_TOKEN": "test_bot_secret"}
