"""Auth de webhook por header-token, comparação tempo-constante. Compartilhado (asaas + bot).

Ambos os webhooks (Asaas e Evolution/WhatsApp) autenticam por um segredo compartilhado que viaja
num header customizado. Só o NOME do header muda; a checagem é idêntica — mora aqui pra não driftar
(hardening de segurança num lado sem o outro).
"""

import hmac

from django.conf import settings


def header_token_matches(request, header: str, expected: str) -> bool:
    """True se `request.headers[header]` bate com `expected` (tempo-constante).

    `expected` vazio (segredo não configurado no .env) => False: fail-closed, o webhook 401a e nada
    é processado.
    """
    if not expected:
        return False
    got = request.headers.get(header, "")
    return hmac.compare_digest(got, expected)


def service_secret_ok(request) -> bool:
    """True se o header de segredo de serviço interno bate — libera o login SEM OTP (bot_v2).

    Mesmo mecanismo dos webhooks (não driftar). Fail-closed: sem BOT_SERVICE_SECRET no .env => False,
    e o caminho send_otp=false recusa emitir JWT.
    """
    return header_token_matches(
        request, settings.BOT_SERVICE_HEADER, settings.BOT_SERVICE_SECRET
    )


def cron_secret_ok(request) -> bool:
    """True se o header de autenticação do Cron Trigger bate.

    Segregação de privilégios: verifica CRON_SERVICE_SECRET via CRON_SERVICE_HEADER.
    Fallback seguro: se CRON_SERVICE_SECRET não estiver configurado, aceita BOT_SERVICE_SECRET.
    """
    cron_secret = getattr(settings, "CRON_SERVICE_SECRET", None) or getattr(
        settings, "BOT_SERVICE_SECRET", ""
    )
    cron_header = getattr(settings, "CRON_SERVICE_HEADER", "x-cron-secret")

    if header_token_matches(request, cron_header, cron_secret):
        return True
    return header_token_matches(request, settings.BOT_SERVICE_HEADER, cron_secret)

