"""View PÚBLICA do infinitepay — o webhook que a InfinitePay chama de volta.

Sem auth de header (a doc oficial não tem); a trava é o `order_nsu` opaco + a reconfirmação via
payment_check dentro do handle_event. O status/checkout eram DMZ sem-auth e foram FECHADOS (Victor
2026-06-16): a saúde da integração vive no grupo Ninja `staff` (require_superuser); o lead consome
checkout in-process (nunca por HTTP).
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.net import source_ip as _source_ip

from . import webhooks


@csrf_exempt
@require_POST
def webhook(request):
    """Receiver de eventos da InfinitePay (PÚBLICO). Sem auth de header (a doc não tem).

    O `order_nsu` (UUID opaco) chega na query; o pagamento é reconfirmado via payment_check antes de
    marcar pago. Responde sempre 200 (a InfinitePay re-tenta se não-200; o evento bruto já fica salvo).
    """
    order_nsu = request.GET.get("order_nsu")
    payload = _parse_json(request)
    _, result = webhooks.handle_event(
        order_nsu,
        payload,
        source_ip=_source_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return JsonResponse(result)


def _parse_json(request):
    """Corpo JSON do request como dict (ou {} se vazio/malformado)."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
