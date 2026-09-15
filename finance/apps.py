from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = "finance"
    label = "finance"

    def ready(self):
        # Registra o system check de config (padrão notify/integrations): avisa se um valor de
        # comissão ficou <= 0 (config quebrada). Warning, não trava — app interno de apoio.
        from django.core.checks import register

        from .checks import check_finance_config

        register(check_finance_config)
