"""Config mínima obrigatória do notify-server."""

from django.conf import settings
from django.core.checks import Error as DjangoError


def check_notify_env(app_configs, **kwargs):
    errors = []
    if not (
        getattr(settings, "NOTIFY_SERVER_URL", "")
        and getattr(settings, "NOTIFY_API_KEY", "")
    ):
        errors.append(
            DjangoError(
                "NOTIFY_SERVER_URL e NOTIFY_API_KEY são obrigatórios.",
                hint="Configure o notify-server no .env.",
                id="notify.E001",
            )
        )
    return errors
