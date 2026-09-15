"""Auth dos endpoints que o Asaas chama de volta (webhook de eventos + validação de saque).

Mecanismo REAL do Asaas (doc oficial): header `asaas-access-token` = um authToken definido no
painel e ecoado em toda chamada. NÃO existe HMAC `asaas-signature` (era delírio do legado). Um
token só pros dois endpoints: `ASAAS_WEBHOOK_SECRET` no `.env` (fonte de verdade).
"""

from core.webhook_auth import header_token_matches

ACCESS_TOKEN_HEADER = "asaas-access-token"


def check_access_token(request, expected=None):
    """True se o header asaas-access-token bate com o token esperado (comparação tempo-constante)."""
    if expected is None:
        from core.system_config import get_setting
        from django.conf import settings
        expected = get_setting("ASAAS_WEBHOOK_SECRET", getattr(settings, "ASAAS_WEBHOOK_SECRET", ""))
    return header_token_matches(request, ACCESS_TOKEN_HEADER, expected)
