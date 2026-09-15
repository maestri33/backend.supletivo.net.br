# Root conftest: garante que DATABASE_URL='sqlite:///:memory:' esteja setado
# antes do pytest-django inicializar o Django settings.
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from tests.conftest import *  # noqa: F401, F403
