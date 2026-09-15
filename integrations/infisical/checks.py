"""System checks do Django para monitoramento da integração Infisical."""

from django.core.checks import CheckMessage, Warning as DjangoWarning
from django.conf import settings

from core.system_config import get_setting


def check_infisical_env(app_configs, **kwargs) -> list[CheckMessage]:
    """Verifica se os parâmetros básicos do Infisical estão declarados."""
    warnings: list[CheckMessage] = []

    base_url = get_setting("INFISICAL_BASE_URL") or getattr(settings, "INFISICAL_BASE_URL", "")
    client_id = get_setting("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID") or getattr(
        settings, "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", ""
    )
    token = get_setting("INFISICAL_TOKEN") or getattr(settings, "INFISICAL_TOKEN", "")

    if not base_url:
        warnings.append(
            DjangoWarning(
                "INFISICAL_BASE_URL não está configurado.",
                id="infisical.W001",
                hint="Configure INFISICAL_BASE_URL apontando para o host do cofre (ex: http://10.0.1.61:8080).",
            )
        )

    if not client_id and not token:
        warnings.append(
            DjangoWarning(
                "Nenhuma credencial de autenticação com o Infisical configurada (Universal Auth ou Token).",
                id="infisical.W002",
                hint="Configure INFISICAL_UNIVERSAL_AUTH_CLIENT_ID + SECRET ou INFISICAL_TOKEN.",
            )
        )

    return warnings
