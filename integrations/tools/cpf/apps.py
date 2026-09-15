from django.apps import AppConfig


class CpfConfig(AppConfig):
    # Tool de CPF (CPFHub.io). Tem api-key (header x-api-key) -> system check avisa se faltar
    # (cpf.W001, Warning — NÃO trava o manage.py: é tool de apoio, diferente do asaas/ia que travam).
    name = "integrations.tools.cpf"
    label = "cpf"

    def ready(self):
        # Registra o system check de env no boot (avisa enquanto faltar a key — cpf.W001).
        from django.core.checks import register

        from .checks import check_cpf_env

        register(check_cpf_env)
