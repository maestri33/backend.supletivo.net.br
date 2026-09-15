"""Helpers de rede compartilhados: IP de origem do cliente + allowlist por IP/CIDR (DMZ).

`source_ip` era TRIPLICADO em bot/views.py, integrations/bank/infinitepay/views.py e
integrations/bank/asaas/views.py — centralizado aqui (DRY), comportamento idêntico.
"""

from __future__ import annotations

import ipaddress


def source_ip(request):
    """IP de origem para LOG/AUDITORIA (consent, webhooks): o 1º IP do X-Forwarded-For (o que o
    cliente REIVINDICA), senão REMOTE_ADDR. NÃO use para decisão de acesso — é forjável pelo cliente
    (o cliente controla o XFF esquerdo). Para gate por IP use `client_ip()`."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def client_ip(request):
    """IP CONFIÁVEL do cliente para DECISÃO DE ACESSO (allowlist/gate). Ao contrário de `source_ip`,
    NÃO confia no XFF esquerdo (forjável). Cada proxy confiável APPENDA o peer real ao XFF, então o
    IP real do cliente é o `settings.TRUSTED_PROXY_COUNT`-ésimo contando da DIREITA; o que estiver à
    esquerda disso é reivindicação não-confiável. Sem XFF suficiente → REMOTE_ADDR (conexão direta)."""
    from django.conf import settings

    n = max(1, int(getattr(settings, "TRUSTED_PROXY_COUNT", 1)))
    xff = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if len(parts) >= n:
        return parts[-n]
    return request.META.get("REMOTE_ADDR")


def ip_allowed(ip, allowlist) -> bool:
    """`ip` está em algum IP/CIDR de `allowlist`? False se `ip` ausente/inválido."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if addr in network:
            return True
    return False


def require_internal_ip(request) -> None:
    """Gate por IP (DMZ) das rotas de `api/tools.py`, que não têm auth de usuário: 403 se o
    `client_ip` não estiver em `settings.TOOLS_ALLOWED_IPS`.

    ponytail: guarda chamada na 1ª linha da rota, não decorator. Como decorator ela precisava
    reconstruir a função com os globals do módulo do view (`types.FunctionType`) pro Ninja
    resolver as anotações string de `from __future__ import annotations`. São 2 rotas, num
    arquivo só. Se virarem muitas, promova a um `auth=` callable do Ninja (401, não 403).
    """
    from django.conf import settings
    from ninja.errors import HttpError

    if not ip_allowed(client_ip(request), settings.TOOLS_ALLOWED_IPS):
        raise HttpError(403, "IP não autorizado.")
