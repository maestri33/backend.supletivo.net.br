"""Hook de pagamento do lead (CONVENTION §7.3).

Registrado em `core.hooks` no boot (`users` AppConfig.ready) para o evento `payment.paid`. O webhook
do Asaas/InfinitePay (`integrations/bank/*`) valida o pagamento, mexe só no próprio estado e então
`dispatch("payment.paid", ...)` — este handler casa o `Checkout` do lead e dispara os efeitos.
"""

from __future__ import annotations


def on_payment_paid(
    *, provider: str, provider_payment_id: str, amount_cents=None, receipt_url=None
) -> bool:
    """True se o pagamento era de um lead (consumido); False senão (webhook cai no fallback rastreável)."""
    from users.roles.lead.service import mark_paid

    return mark_paid(
        provider=provider,
        provider_payment_id=provider_payment_id,
        receipt_url=receipt_url,
    )


def on_payment_refunded(
    *, provider: str, provider_payment_id: str, amount_cents=None
) -> bool:
    """True se o estorno era de um lead (consumido); False senão."""
    from users.roles.lead.service import mark_refunded

    return mark_refunded(
        provider=provider,
        provider_payment_id=provider_payment_id,
    )

