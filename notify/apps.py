from django.apps import AppConfig


class NotifyConfig(AppConfig):
    name = "notify"
    label = "notify"

    def ready(self):
        from django.core.checks import register

        from .checks import check_notify_env

        register(check_notify_env)
