"""Models do app integrations.bank.asaas — porte do micro legado (SQLAlchemy) pro ORM Django.

Convenções (CONVENTION §4/§6/§8):
 - PK = BigAutoField interno (Django). Nunca é exposto.
 - `external_id` (UUID) = id de borda exposto na API. `asaas_id` = id do lado do Asaas.
 - Referência entre models do MESMO domínio (asaas) é FK de verdade — acabou o
   `external_id` como cola interna (era assim no micro legado; aqui não).
 - Dinheiro é Decimal, nunca float.
 - Aqui é só o schema. As máquinas de status do Payment ficam como string/choices; a lógica
   que transiciona entra nas etapas charge/payout (1a-iv / 1a-v).
"""

from django.db import models

from core.models import ExternalIdModel


class Customer(ExternalIdModel):
    """Pagadores cadastrados no Asaas (find-or-create).

    Necessário pra criar cobranças (Payment kind=charge): o Asaas /payments exige customer_id.
    Guardamos o mapeamento external_id (borda) -> asaas_id pra não duplicar customer a cada
    cobrança.
    """

    asaas_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    cpf_cnpj = models.CharField(max_length=14, db_index=True)
    email = models.EmailField(null=True, blank=True)
    mobile_phone = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.asaas_id})"


class PixKey(ExternalIdModel):
    """Chaves PIX validadas no DICT e registradas no nosso namespace.

    `external_id` (borda) é como o resto do sistema referencia a chave; `key` é a chave PIX.
    """

    key = models.CharField(max_length=255, unique=True)
    key_type = models.CharField(max_length=10)  # CPF | CNPJ | EMAIL | PHONE | EVP
    holder_document = models.CharField(
        max_length=14, db_index=True
    )  # CPF(11) ou CNPJ(14)
    holder_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    validated_at = models.DateTimeField(auto_now_add=True)
    raw_dict = models.JSONField(default=dict)  # resposta bruta do DICT

    def __str__(self):
        return f"{self.key} ({self.key_type})"


class Payment(models.Model):
    """Pagamentos PIX — outbound (kind=pixkey|qrcode) e inbound (kind=charge).

    kind=pixkey -> transferência pra chave PIX cadastrada (outbound)
    kind=qrcode -> pagamento de BR Code copia-e-cola (outbound)
    kind=charge -> cobrança PIX recebida via Asaas /payments (inbound)
    kind=boleto -> pagamento de boleto/conta por linha digitável (outbound) — /v3/bill
    """

    class Kind(models.TextChoices):
        PIXKEY = "pixkey"
        QRCODE = "qrcode"
        CHARGE = "charge"
        BOLETO = "boleto"
        STATIC_PIX_QR = "static_pix_qr"  # QR Code PIX estático direto (baixo custo)

    # `status` é string livre por ora; a máquina/choices entra nas etapas que transicionam.
    # outbound: SCHEDULED|QUEUED|SUBMITTING|SUBMITTED|AWAITING_BALANCE|PAID|FAILED|CANCELLED|
    #           NEEDS_RECONCILE
    # charge:   PENDING|PAID|EXPIRED|CANCELLED|REFUNDED
    payment_id = models.CharField(
        max_length=255, unique=True
    )  # ref pública (user-provided/uuid)
    kind = models.CharField(max_length=14, choices=Kind.choices, db_index=True)

    # kind=pixkey -> FK real pra PixKey (CONVENTION §4: referência interna é FK, não string-cola)
    pix_key = models.ForeignKey(
        "PixKey",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    # kind=qrcode (BR Code pago) e kind=charge (BR Code retornado pelo Asaas)
    qrcode_payload = models.TextField(null=True, blank=True)
    # kind=charge -> FK real pra Customer
    customer = models.ForeignKey(
        "Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    # Meio de pagamento específico da cobrança inbound (PIX, BOLETO, CREDIT_CARD, UNDEFINED)
    billing_type = models.CharField(
        max_length=20, null=True, blank=True, db_index=True
    )
    pix_qr_image = models.TextField(
        null=True, blank=True
    )  # PNG base64 do QR (kind=charge)
    bank_slip_url = models.URLField(
        max_length=500, null=True, blank=True
    )  # URL do PDF do boleto bancário
    identification_field = models.CharField(
        max_length=128, null=True, blank=True
    )  # Linha digitável do boleto
    nosso_numero = models.CharField(
        max_length=64, null=True, blank=True
    )  # Identificador bancário
    installment_count = models.PositiveSmallIntegerField(
        null=True, blank=True
    )  # Parcelas no cartão
    credit_card_brand = models.CharField(
        max_length=32, null=True, blank=True
    )  # Bandeira do cartão
    credit_card_last_digits = models.CharField(
        max_length=4, null=True, blank=True
    )  # Últimos 4 dígitos
    net_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )  # Valor líquido após taxas do gateway
    due_date = models.DateField(null=True, blank=True)  # vencimento da cobrança
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(null=True, blank=True)
    scheduled_for = models.DateTimeField(
        null=True, blank=True
    )  # NULL = imediato (outbound)
    status = models.CharField(max_length=20, db_index=True)
    asaas_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.payment_id} [{self.kind}] {self.status}"


class WebhookEvent(models.Model):
    """Payloads brutos recebidos do Asaas.

    O POST /webhook/ é público externo (CONVENTION §7): guardamos source_ip (resolve
    X-Forwarded-For atrás do proxy) e user_agent da origem.
    """

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    event = models.CharField(max_length=255, db_index=True)
    payload = models.JSONField(default=dict)
    forwarded_ok = models.BooleanField(default=False)
    forwarded_at = models.DateTimeField(null=True, blank=True)
    source_ip = models.CharField(max_length=64, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.event} @ {self.received_at:%Y-%m-%d %H:%M:%S}"


class UrlVerifyNonce(models.Model):
    """Nonces emitidos durante a validação de URL (externa/interna)."""

    nonce = models.CharField(max_length=255, primary_key=True)
    target_url = models.TextField()
    purpose = models.CharField(max_length=10)  # external | internal
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.nonce} ({self.purpose})"
