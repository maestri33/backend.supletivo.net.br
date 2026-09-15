from django.apps import AppConfig


class InfinitepayConfig(AppConfig):
    name = "integrations.bank.infinitepay"
    label = "infinitepay"

    def ready(self):
        # Registra o system check de env no boot (roda em todo runserver/manage). Sem o handle o app
        # não fala com a InfinitePay → infinitepay.E001 trava (a InfinitePay não usa api-key).
        from django.core.checks import register

        from .checks import check_infinitepay_handle

        register(check_infinitepay_handle)
