"""Models do app integrations.bank.infinitepay — porte do micro legado pro ORM Django.

Convenções (CONVENTION §4/§6/§8):
 - PK = BigAutoField interno (Django), nunca exposto.
 - `external_id` (UUID) = id de borda E o `order_nsu` enviado à InfinitePay (token opaco que liga o
   webhook ao checkout — impossível de adivinhar). `slug` = id da fatura no lado da InfinitePay.
 - Dinheiro em CENTAVOS (int) — é como a API da InfinitePay fala (price/amount em centavos).
 - Status só vira PAID por reconfirmação via payment_check (webhooks.py), nunca por confiar no corpo
   do webhook. Aqui é só o schema.
"""

from django.db import models

from core.models import ExternalIdModel


class Checkout(ExternalIdModel):
    """Link de pagamento InfinitePay (cartão/pix). Um por cobrança."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PAID = "PAID"

    # external_id (herdado de ExternalIdModel) = borda (CONVENTION §4) E o order_nsu enviado à InfinitePay.
    checkout_url = models.TextField(null=True, blank=True)
    slug = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )  # invoice_slug do lado da InfinitePay
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    amount_cents = models.IntegerField()
    paid_amount_cents = models.IntegerField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    installments = models.IntegerField(null=True, blank=True)
    capture_method = models.CharField(
        max_length=32, null=True, blank=True
    )  # pix | credit_card
    transaction_nsu = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )
    receipt_url = models.TextField(null=True, blank=True)
    request_payload = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.external_id} [{self.status}] {self.amount_cents}c"


class WebhookEvent(models.Model):
    """Payloads brutos recebidos da InfinitePay (auditoria — mesmo padrão do asaas.WebhookEvent).

    O POST /webhook/ é público externo (CONVENTION §7): guardamos source_ip (resolve X-Forwarded-For
    atrás do proxy) e user_agent da origem.
    """

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    order_nsu = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    forwarded_ok = models.BooleanField(default=False)
    forwarded_at = models.DateTimeField(null=True, blank=True)
    source_ip = models.CharField(max_length=64, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.order_nsu} @ {self.received_at:%Y-%m-%d %H:%M:%S}"
