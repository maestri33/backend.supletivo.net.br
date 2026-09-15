"""System checks do app infinitepay — avisam no boot quando falta env essencial.

Mesmo padrão do asaas (CONVENTION §8): integração não sobe silenciosa sem o necessário. A InfinitePay
autentica SÓ pelo `handle` (InfiniteTag) — não existe api-key —, então o que TRAVA o manage é o
`INFINITEPAY_HANDLE`. Sem ele, nem dá pra criar link de checkout.
"""

from django.conf import settings
from django.core.checks import Error


def check_infinitepay_handle(app_configs, **kwargs):
    """Erra se INFINITEPAY_HANDLE não estiver no .env — sem ele o app não fala com a InfinitePay."""
    errors = []
    if not getattr(settings, "INFINITEPAY_HANDLE", ""):
        errors.append(
            Error(
                "INFINITEPAY_HANDLE ausente no .env — o app infinitepay não consegue criar links na "
                "InfinitePay.",
                hint="Cole o handle (InfiniteTag, sem o $) em backend/.env: INFINITEPAY_HANDLE=...",
                id="infinitepay.E001",
            )
        )
    return errors
