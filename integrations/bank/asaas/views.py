"""Views PÚBLICAS do asaas — o que o Asaas chama de volta (1a-iii).

Auth dos webhooks = só o header `asaas-access-token` == ASAAS_WEBHOOK_SECRET no .env (sem HMAC — não
existe no Asaas). A url-verify usa nonce single-use + TTL. O onboarding/health (status/setup) e
charge/payout eram DMZ sem-auth e foram FECHADOS (Victor 2026-06-16): a saúde e as ações da integração
vivem no grupo Ninja `staff` (require_superuser), que chama os módulos onboarding/charge/payout
in-process. O lead/finance também consomem charge/payout in-process (nunca por HTTP).
"""

import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.net import source_ip as _source_ip

from . import transfer_validation as tv
from . import url_verify
from . import webhooks
from .security import check_access_token


@require_GET
def url_verify_echo(request, nonce):
    """Echo PÚBLICO do ping de verificação de URL: consome o nonce single-use e responde 200.

    Auth = o próprio nonce secreto single-use + TTL (CONVENTION §5 público). Que o nonce seja
    consumido prova que a chamada à EXTERNAL_URL chegou NESTE backend.
    """
    ok, reason = url_verify.consume_nonce(nonce)
    return JsonResponse({"ok": ok, "reason": reason}, status=200 if ok else 404)


@csrf_exempt
@require_POST
def webhook(request):
    """Receiver de eventos do Asaas (PÚBLICO). Auth: asaas-access-token == ASAAS_WEBHOOK_SECRET.

    Token inválido/ausente → 401. Autenticado → persiste+roteia e responde 200 (Asaas re-tenta se
    não-200; o evento bruto já fica salvo antes do roteamento).
    """
    if not check_access_token(request):
        return JsonResponse({"detail": "invalid_token"}, status=401)
    payload = _parse_json(request)
    webhooks.handle_event(
        payload,
        source_ip=_source_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def transfer_validation(request):
    """Mecanismo de validação de saque do Asaas (PÚBLICO). Auth: asaas-access-token == .env.

    Token inválido/ausente → 401 (Asaas cancela a saída após 3 falhas = seguro). Autenticado →
    decide APPROVED/REFUSED contra o nosso DB.
    """
    if not check_access_token(request):
        return JsonResponse({"detail": "invalid_token"}, status=401)
    return JsonResponse(tv.decide(_parse_json(request)))


def _parse_json(request):
    """Corpo JSON do request como dict (ou {} se vazio/malformado)."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
