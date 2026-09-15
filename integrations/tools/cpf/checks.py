"""System check do app cpf — avisa no boot quando falta a api-key.

Diferente do asaas/ia (key ausente = Error que TRAVA o manage.py, pois são caminho de dinheiro/IA),
aqui é Warning: CPF é tool de apoio e não deve travar a migração do monólito inteiro (decisão do
plan 1d-cpf). Na prática nem dispara — a key já está no .env.
"""

from django.conf import settings
from django.core.checks import Warning


def check_cpf_env(app_configs, **kwargs):
    """Avisa (não trava) se CPFHUB_API_KEY faltar — sem ela o lookup levanta CpfHubError."""
    if getattr(settings, "CPFHUB_API_KEY", ""):
        return []
    return [
        Warning(
            "CPFHUB_API_KEY ausente no .env — o lookup de CPF (integrations.tools.cpf) "
            "vai levantar CpfHubError.",
            hint="Cole a api-key da CPFHub em backend/.env: CPFHUB_API_KEY=...",
            id="cpf.W001",
        )
    ]
