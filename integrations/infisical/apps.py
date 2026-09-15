"""AppConfig para a integração com Infisical Vault."""

from django.apps import AppConfig


class InfisicalConfig(AppConfig):
    name = "integrations.infisical"
    label = "infisical"

    def ready(self):
        from django.core.checks import register
        from .checks import check_infisical_env

        register(check_infisical_env)
