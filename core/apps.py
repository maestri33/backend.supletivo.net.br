from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    label = "core"

    def ready(self):
        # Observabilidade: avisa (não trava) quando prod sobe sem Sentry, ou com o corpo do
        # request ligado no evento. O init do SDK em si já rodou lá no settings.
        from django.core.checks import register

        from .checks import check_sentry

        register(check_sentry)

        # Sincronização automática com Infisical se configurado
        from django.conf import settings
        auto_sync = getattr(settings, "INFISICAL_AUTO_SYNC", False)
        if auto_sync:
            try:
                from integrations.infisical import sync_secrets_to_platform
                sync_secrets_to_platform()
            except Exception:
                pass
