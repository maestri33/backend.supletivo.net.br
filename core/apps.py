from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    label = "core"

    def ready(self):
        # Observabilidade: avisa (não trava) quando prod sobe sem Sentry, ou com o corpo do
        # request ligado no evento. O init do SDK em si já rodou lá no settings.
        from django.core.checks import register

        from .checks import check_sentry
        from .system_config import load_all_settings_into_cache, get_setting

        register(check_sentry)
        load_all_settings_into_cache()

        # Sincronização automática com Infisical se configurado
        from django.conf import settings
        auto_sync = getattr(settings, "INFISICAL_AUTO_SYNC", False) or get_setting("INFISICAL_AUTO_SYNC") in ("1", "true", "True")
        if auto_sync:
            try:
                from integrations.infisical import sync_secrets_to_platform
                sync_secrets_to_platform()
            except Exception:
                pass
