"""System checks do app asaas — avisam no boot quando falta env essencial.

Rodam em todo runserver/manage (framework de checks do Django), então ficam "printando" até a env
ser preenchida. Padrão pedido pelo Victor: integração não sobe silenciosa sem credencial real
(CONVENTION §8).

- `asaas.E001` (Error): sem ASAAS_API_KEY o app NÃO fala com o Asaas → TRAVA o manage.py.
- `asaas.W001` (Warning): sem ASAAS_WEBHOOK_SECRET os webhooks dão 401 → avisa recorrente, NÃO trava
  (não faz sentido travar migração por falta de token de webhook).
"""

from django.conf import settings
from django.core.checks import Error, Warning


def check_asaas_env(app_configs, **kwargs):
    """Erra se ASAAS_API_KEY não estiver no .env — sem ela o app não fala com o Asaas."""
    errors = []
    if not getattr(settings, "ASAAS_API_KEY", ""):
        errors.append(
            Error(
                "ASAAS_API_KEY ausente no .env — o app asaas não consegue falar com o Asaas.",
                hint="Cole a api-key do Asaas em backend/.env: ASAAS_API_KEY=...",
                id="asaas.E001",
            )
        )
    return errors


def check_asaas_webhook_secret(app_configs, **kwargs):
    """Avisa (não trava) se ASAAS_WEBHOOK_SECRET faltar — sem ele os webhooks do Asaas dão 401."""
    warnings = []
    if not getattr(settings, "ASAAS_WEBHOOK_SECRET", ""):
        warnings.append(
            Warning(
                "ASAAS_WEBHOOK_SECRET ausente no .env — webhooks do Asaas (eventos e validação de "
                "saque) vão responder 401.",
                hint="Acesse GET /integrations/asaas/status/, copie o generated_webhook_secret pra "
                "ASAAS_WEBHOOK_SECRET no .env e cole o MESMO valor no painel do Asaas.",
                id="asaas.W001",
            )
        )
    return warnings
