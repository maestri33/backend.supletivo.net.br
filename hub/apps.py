from django.apps import AppConfig


class HubConfig(AppConfig):
    name = "hub"
    label = "hub"

    def ready(self):
        from django.core.checks import register

        from hub.checks import check_hub_config

        register(check_hub_config)
