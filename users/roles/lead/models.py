"""Lead — a 1ª role do funil do ALUNO (clients): capta → paga → vira enrollment.

Porte do legado (`~/coders/backend` lead/), adaptado ao monólito: **FK real** (não external_id interno,
§4). O Lead **nasce ligado a um PROMOTER** (o `?ref=` da landing; sem ref → promotor padrão) — palavra do
Victor 2026-06-04. Ao PAGAR, vira `enrollment` (deixa de ser do promotor, passa a ser cuidado pelo hub).

Máquina de status REDUZIDA (Victor 2026-06-04, plano §6-lead-funil: o método já vem na criação e o
checkout é gerado síncrono → somem `captured`/`waiting`/`checkout` do legado):
`PENDING` (criado + checkout gerado, aguardando pagar) → `PAID` (webhook confirmou → efeitos) | `FAILED`
(gateway falhou ao gerar, ou pagamento expirou/cancelou). O detalhe (método/QR/link/pago) fica no
`Checkout`; `Lead.status` é só o estado que a API/gate enxergam. Sub-pacote de `users` (app_label
`users`, 1 migration set — igual address/documents; CONVENTION §2).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel


class Lead(ExternalIdModel):
    """Um lead (aspirante a aluno). 1-1 com o User; ligado ao promotor que o captou."""

    class Status(models.TextChoices):
        PENDING = "pending", "aguardando pagamento"
        PAID = "paid", "pago"
        FAILED = "failed", "falhou"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lead",
    )
    # o promotor que captou (ref da landing; nunca nulo — lead não existe sem promotor, Victor 2026-06-04).
    promoter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="captured_leads",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    failed_reason = models.CharField(max_length=64, null=True, blank=True)
    # auto-matrícula do PROMOTOR que quis estudar (Victor 2026-06-16): preço próprio, SEM comissão a
    # ninguém. `promoter` aponta pro próprio user (FK não-nulável); a comissão é barrada por este flag.
    self_study = models.BooleanField(default=False, db_index=True)

    # ── Snapshot imutável de precificação na captura (Anti-poaching / Proteção de Proposta) ──
    pix_price = models.DecimalField(
        "preço PIX travado", max_digits=10, decimal_places=2, null=True, blank=True
    )
    card_price = models.DecimalField(
        "preço cartão travado", max_digits=10, decimal_places=2, null=True, blank=True
    )
    card_installments = models.PositiveSmallIntegerField(
        "parcelas cartão", default=12
    )
    card_installment = models.DecimalField(
        "valor da parcela cartão", max_digits=10, decimal_places=2, null=True, blank=True
    )
    anchor_price = models.DecimalField(
        "preço âncora travado", max_digits=10, decimal_places=2, null=True, blank=True
    )
    has_discount = models.BooleanField("desconto promocional aplicado", default=False)
    promoter_name = models.CharField(
        "nome do promotor na captura", max_length=150, blank=True, default=""
    )
    pricing_snapshot = models.JSONField(
        "snapshot completo dos valores na captura", default=dict, blank=True
    )

    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_lead"
        verbose_name = "lead"
        verbose_name_plural = "leads"

    def __str__(self) -> str:
        return f"lead<{self.external_id}:{self.status}>"

    def lock_pricing(self, ref: str | None = None) -> None:
        """Calcula e trava as condições de preço do lead no momento da criação/captura."""
        from decimal import Decimal
        from finance import config as fin_config
        from users.roles.lead import config
        from users.roles.lead import service as lead_svc

        if self.pix_price and self.card_price and self.pricing_snapshot:
            return  # já travado, imutável

        installments = 12
        anchor = config.anchor_full()
        anchor_inst = (anchor / installments).quantize(Decimal("0.01"))

        if self.self_study:
            pix = config.promoter_price_pix()
            card = config.promoter_price_card()
            has_disc = True
            p_name = None
        else:
            resolved_ref = ref
            if not resolved_ref and hasattr(self, "attribution") and self.attribution:
                resolved_ref = self.attribution.ref_raw

            name = lead_svc.referral_name(resolved_ref) if resolved_ref else None
            if name:
                has_disc = True
                p_name = name
                pix = config.promo_price_pix()
                card = config.promo_price_card()
            else:
                has_disc = False
                p_name = None
                pix = config.price_pix()
                card = config.price_card()

        card_inst = (card / installments).quantize(Decimal("0.01"))

        self.pix_price = pix
        self.card_price = card
        self.card_installments = installments
        self.card_installment = card_inst
        self.anchor_price = anchor
        self.has_discount = has_disc
        self.promoter_name = p_name or ""

        self.pricing_snapshot = {
            "pix": f"{pix:.2f}",
            "card": {
                "installments": installments,
                "installment": f"{card_inst:.2f}",
                "total": f"{card:.2f}",
            },
            "promo_pix": f"{config.promo_price_pix():.2f}" if has_disc else None,
            "promo_card": {
                "installments": installments,
                "installment": f"{(config.promo_price_card() / installments).quantize(Decimal('0.01')):.2f}",
                "total": f"{config.promo_price_card():.2f}",
            } if has_disc else None,
            "has_discount": has_disc,
            "promoter_name": p_name,
            "anchor_full": f"{anchor:.2f}",
            "commission_direct": f"{fin_config.direct_amount():.2f}",
            "commission_bonus_flat": f"{fin_config.bonus_amount():.2f}",
            "commission_bonus_threshold": fin_config.bonus_threshold(),
            "commission_coordinator": f"{fin_config.coordinator_amount():.2f}",
        }

    def get_pricing_dict(self) -> dict:
        """Devolve o snapshot de preços travado do lead."""
        if not self.pix_price or not self.pricing_snapshot:
            self.lock_pricing()
            if self.pk:
                Lead.objects.filter(pk=self.pk).update(
                    pix_price=self.pix_price,
                    card_price=self.card_price,
                    card_installments=self.card_installments,
                    card_installment=self.card_installment,
                    anchor_price=self.anchor_price,
                    has_discount=self.has_discount,
                    promoter_name=self.promoter_name,
                    pricing_snapshot=self.pricing_snapshot,
                )
        return self.pricing_snapshot

    def save(self, *args, **kwargs):
        if not self.pix_price or not self.pricing_snapshot:
            self.lock_pricing()
        super().save(*args, **kwargs)


class Checkout(models.Model):
    """O checkout de pagamento de um lead (1-1). Reusa os gateways `integrations/bank/{asaas,infinitepay}`."""

    class Method(models.TextChoices):
        CREDIT_CARD = "credit_card", "cartão de crédito"
        PIX = "pix", "PIX"

    class Provider(models.TextChoices):
        ASAAS = "asaas", "Asaas"
        INFINITEPAY = "infinitepay", "InfinitePay"

    lead = models.OneToOneField(
        Lead,
        on_delete=models.CASCADE,
        related_name="checkout",
    )
    payment_method = models.CharField(max_length=12, choices=Method.choices)
    provider = models.CharField(max_length=12, choices=Provider.choices)
    provider_payment_id = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # cartão (InfinitePay) = link de checkout do gateway; PIX = a NOSSA página `/pix/<token>` (o QR
    # estático do Asaas não tem fatura hospedada — issue #158). + comprovante pós-pagamento.
    checkout_url = models.URLField(max_length=500, null=True, blank=True)
    receipt_url = models.URLField(max_length=500, null=True, blank=True)
    # token do link CURTO no nosso domínio (/lead/checkout/<token> → 302 pro checkout). Ver checkout_links.
    short_token = models.CharField(max_length=32, null=True, blank=True, db_index=True)
    # PIX (Asaas): copia-e-cola + imagem do QR + vencimento.
    qrcode_payload = models.TextField(null=True, blank=True)
    qrcode_image = models.URLField(max_length=500, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    is_paid = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_lead_checkout"
        verbose_name = "checkout do lead"
        verbose_name_plural = "checkouts do lead"

    def __str__(self) -> str:
        return f"checkout<{self.lead_id}:{self.payment_method}:{'pago' if self.is_paid else 'pendente'}>"


class LeadAttribution(models.Model):
    """Rastreamento de aquisição e atribuição de tráfego do lead (UTMs, click IDs, cookies Meta e rede)."""

    lead = models.OneToOneField(
        Lead,
        on_delete=models.CASCADE,
        related_name="attribution",
    )
    ref_raw = models.CharField(max_length=64, blank=True)
    utm_source = models.CharField(max_length=128, blank=True)
    utm_medium = models.CharField(max_length=128, blank=True)
    utm_campaign = models.CharField(max_length=128, blank=True)
    utm_term = models.CharField(max_length=128, blank=True)
    utm_content = models.CharField(max_length=128, blank=True)
    gclid = models.CharField(max_length=255, blank=True, db_index=True)
    fbclid = models.CharField(max_length=255, blank=True)
    fbp = models.CharField(max_length=64, blank=True)
    fbc = models.CharField(max_length=255, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    landing_url = models.URLField(max_length=500, blank=True)
    sent_google = models.DateTimeField(null=True, blank=True)
    sent_meta = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        app_label = "users"
        db_table = "users_lead_attribution"
        verbose_name = "atribuição do lead"
        verbose_name_plural = "atribuições dos leads"

    def __str__(self) -> str:
        return f"lead_attribution<{self.lead_id}:{self.ref_raw or 'direct'}>"

