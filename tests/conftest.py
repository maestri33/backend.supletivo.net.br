# ponytail: fixtures mínimos — db + client. SQLite em memória para testes.
import os

# Força SQLite ANTES do Django ler settings (sobrescreve o .env).
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from django.test import Client


@pytest.fixture(autouse=True)
def test_settings():
    from django.conf import settings

    settings.TEST_MODE = True
    settings.APP_ENV = "test"
    settings.BOT_SERVICE_SECRET = "test_bot_secret"
    settings.BOT_SERVICE_HEADER = "x-bot-service-token"


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def bot_headers():
    return {"HTTP_X_BOT_SERVICE_TOKEN": "test_bot_secret"}
