"""Short-lived, staff-authorized canaries bound to frozen purchase proposals.

The global commercial settings never participate in this override. Expiration
stops new proposals; signed proposals already issued retain their original terms.
No CPF, telephone, or payment credential is copied into the proposal snapshot.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import PlatformSetting
from finance.models import Commission, FinancialAuditLog, FinancialTransaction, PaymentRequest

CONFIG_KEY = "PRODUCTION_CANARY_RUN"
_SALT = "finance.production-canary.v1"
RULES = {
    "pix": "1.01", "card_total": "1.02", "card_installments": 1,
    "direct": "0.01", "bonus": "0.10", "bonus_threshold": 5,
    "coordinator": "0.05", "max_paid_sources": 5,
}


class CanaryError(ValueError):
    """Fail closed rather than charge/credit the commercial amount for a canary."""


def _digits(value):
    return "".join(char for char in str(value or "") if char.isdigit())


def _phone(value):
    number = _digits(value)
    number = "55" + number if len(number) in (10, 11) else number
    # WhatsApp may store a Brazilian mobile without its optional ninth digit.
    if len(number) == 13 and number.startswith("55") and number[4] == "9":
        number = number[:4] + number[5:]
    return number


def _identity(value):
    result = {"cpf": _digits(value.get("cpf")), "phone": _phone(value.get("phone"))}
    if len(result["cpf"]) != 11 or len(result["phone"]) not in (12, 13) or not result["phone"].startswith("55"):
        raise CanaryError("canary_identity_invalid")
    return result


def _matches(profile, identity):
    return bool(profile and _digits(profile.cpf) == identity["cpf"] and _phone(profile.phone) == identity["phone"])


@transaction.atomic
def configure(*, actor, owner, allowlist, ttl_hours=24, justification):
    """Restricted management-command entry point. Does not create purchases/payouts."""
    if not actor or not actor.is_staff or not actor.is_active:
        raise CanaryError("canary_staff_required")
    if not justification or not justification.strip():
        raise CanaryError("canary_justification_required")
    if not 1 <= ttl_hours <= 72 or len(allowlist) != 2:
        raise CanaryError("canary_bounds_invalid")
    identities = [_identity(item) for item in allowlist]
    if len({(item["cpf"], item["phone"]) for item in identities}) != 2:
        raise CanaryError("canary_allowlist_must_be_distinct")
    profile = getattr(owner, "profile", None)
    if not owner.is_active or not any(_matches(profile, item) for item in identities):
        raise CanaryError("canary_owner_not_allowlisted")
    now = timezone.now()
    value = {
        "active": True, "run_id": str(uuid.uuid4()), "owner_external_id": str(owner.external_id),
        "allowlist": identities, "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
        "actor_external_id": str(actor.external_id),
        "proposal_count": 0,
    }
    previous = PlatformSetting.objects.select_for_update().filter(key=CONFIG_KEY).first()
    if previous:
        old = json.loads(previous.value)
        if old.get("active") and parse_datetime(old["expires_at"]) > now:
            raise CanaryError("canary_run_already_active")
    PlatformSetting.objects.update_or_create(key=CONFIG_KEY, defaults={
        "value": json.dumps(value), "is_secret": True,
        "description": "Canário autorizado: duas identidades, valores fixos, expiração e fonte auditável",
    })
    FinancialAuditLog.objects.create(
        actor=actor, action=FinancialAuditLog.Action.CANARY_CONFIG, target_model="PlatformSetting",
        target_external_id=value["run_id"], justification=justification.strip(),
        snapshot_before={"run_id": old.get("run_id"), "active": old.get("active")} if previous else None,
        snapshot_after={key: value[key] for key in ("run_id", "active", "issued_at", "expires_at", "owner_external_id")},
    )
    return value


@transaction.atomic
def disable(*, actor, justification):
    if not actor or not actor.is_staff or not actor.is_active:
        raise CanaryError("canary_staff_required")
    if not justification or not justification.strip():
        raise CanaryError("canary_justification_required")
    row = PlatformSetting.objects.select_for_update().filter(key=CONFIG_KEY).first()
    if not row:
        return None
    value = json.loads(row.value)
    value["active"] = False
    row.value = json.dumps(value)
    row.save(update_fields=["value", "updated_at"])
    FinancialAuditLog.objects.create(actor=actor, action=FinancialAuditLog.Action.CANARY_CONFIG,
        target_model="PlatformSetting", target_external_id=value["run_id"], justification=justification.strip(),
        snapshot_before={"active": True}, snapshot_after={"active": False, "run_id": value["run_id"]})
    return value["run_id"]


@transaction.atomic
def pricing_snapshot(user):
    """Return private pricing terms only after authenticated CPF AND phone match."""
    row = PlatformSetting.objects.select_for_update().filter(key=CONFIG_KEY).first()
    if not row:
        return None
    try:
        config = json.loads(row.value)
        expires = parse_datetime(config["expires_at"])
        if not config.get("active") or not expires or expires <= timezone.now():
            return None
        if not any(_matches(getattr(user, "profile", None), item) for item in config["allowlist"]):
            return None
        if config.get("proposal_count", 0) >= RULES["max_paid_sources"]:
            raise CanaryError("canary_proposal_limit")
        payload = {"version": 1, "run_id": config["run_id"],
            "source_user_external_id": str(user.external_id), "owner_external_id": config["owner_external_id"],
            "issued_at": timezone.now().isoformat(), "expires_at": config["expires_at"], **RULES}
        config["proposal_count"] = config.get("proposal_count", 0) + 1
        row.value = json.dumps(config)
        row.save(update_fields=["value", "updated_at"])
        return {**payload, "signature": signing.dumps(payload, salt=_SALT, compress=True)}
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CanaryError("canary_config_invalid") from exc


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise CanaryError("canary_snapshot_invalid")
    try:
        payload = signing.loads(snapshot["signature"], salt=_SALT)
        if payload != {key: value for key, value in snapshot.items() if key != "signature"}:
            raise CanaryError("canary_snapshot_tampered")
        for key, value in RULES.items():
            if payload.get(key) != value:
                raise CanaryError("canary_rules_invalid")
        for key in ("run_id", "source_user_external_id", "owner_external_id"):
            uuid.UUID(payload[key])
        issued, expires = parse_datetime(payload["issued_at"]), parse_datetime(payload["expires_at"])
        if payload.get("version") != 1 or not issued or not expires or issued > expires or timezone.is_naive(issued) or timezone.is_naive(expires):
            raise CanaryError("canary_snapshot_dates_invalid")
        return payload
    except (KeyError, TypeError, ValueError, signing.BadSignature) as exc:
        raise CanaryError("canary_snapshot_invalid") from exc


def source_terms(*, source_type, source_external_id, payee):
    """Resolve the purchase itself; merely being the owner never changes commission."""
    from django.apps import apps
    Lead = apps.get_model("users", "Lead")
    Student = apps.get_model("users", "Student")
    if source_type == Commission.Source.LEAD:
        lead = Lead.objects.filter(external_id=source_external_id).select_related("user").first()
    elif source_type == Commission.Source.VETERAN:
        student = Student.objects.filter(external_id=source_external_id).first()
        lead = Lead.objects.filter(user_id=student.user_id).select_related("user").first() if student else None
    else:
        return None
    snapshot = lead.pricing_snapshot.get("canary") if lead and isinstance(lead.pricing_snapshot, dict) else None
    if snapshot is None:
        return None
    terms = validate_snapshot(snapshot)
    if terms["source_user_external_id"] != str(lead.user.external_id) or terms["owner_external_id"] != str(payee.external_id):
        raise CanaryError("canary_source_or_payee_mismatch")
    checkout = getattr(lead, "checkout", None)
    if lead.status != Lead.Status.PAID or not checkout or not checkout.is_paid or not checkout.provider_payment_id:
        raise CanaryError("canary_payment_unconfirmed")
    if checkout.payment_method not in ("pix", "credit_card"):
        raise CanaryError("canary_payment_method_invalid")
    # Persisted provider acknowledgement must correspond to the frozen proposal.
    expected = terms["pix"] if checkout.payment_method == "pix" else terms["card_total"]
    if checkout.amount != Decimal(expected):
        raise CanaryError("canary_checkout_amount_mismatch")
    return snapshot


def record_accrual(item):
    if not item.canary_run_id or item.amount <= 0:
        return
    from finance.interface import ledger
    ledger.record_transaction(kind=FinancialTransaction.Kind.COMMISSION_ACCRUED, amount=item.amount,
        source_type=FinancialTransaction.SourceType.WEEKLY_CLOSING, source_external_id=item.external_id,
        idempotency_key=f"canary-accrual:{item.external_id}", canary_run_id=item.canary_run_id,
        description=f"Despesa de teste {item.canary_run_id}; comissão {item.source_type}; fonte {item.source_external_id}",
        entries=[{"account_code": ledger.ACCOUNT_EXPENSE_COMMISSION, "entry_type": "debit", "amount": item.amount},
                 {"account_code": ledger.ACCOUNT_LIABILITY_PROMOTER, "entry_type": "credit", "amount": item.amount}])


def validate_payout(pr):
    """Before provider I/O: prevent a mixed, inflated or redirected canary batch."""
    items = list(pr.commissions.exclude(status=Commission.Status.CANCELLED))
    runs = {str(item.canary_run_id) if item.canary_run_id else None for item in items}
    if not pr.canary_run_id:
        if any(runs):
            raise CanaryError("canary_batch_mixed")
        return
    if pr.kind != PaymentRequest.Kind.COMMISSION or runs != {str(pr.canary_run_id)} or not items:
        raise CanaryError("canary_batch_mixed")
    amount = Decimal(str(pr.amount))
    if sum((item.amount for item in items), Decimal("0.00")) != amount or not Decimal("0.00") < amount <= Decimal("0.40"):
        raise CanaryError("canary_payout_amount_invalid")
    for item in items:
        terms = validate_snapshot(item.canary_snapshot)
        if terms["run_id"] != str(pr.canary_run_id) or terms["owner_external_id"] != str(pr.payee.external_id) or item.payee_id != pr.payee_id:
            raise CanaryError("canary_payout_recipient_invalid")
        expected = {Commission.Source.LEAD: "direct", Commission.Source.VETERAN: "coordinator", Commission.Source.BONUS: "bonus"}.get(item.source_type)
        if expected and item.amount != Decimal(terms[expected]):
            raise CanaryError("canary_commission_amount_invalid")
        if item.source_type in (Commission.Source.LEAD, Commission.Source.VETERAN):
            if source_terms(source_type=item.source_type, source_external_id=item.source_external_id, payee=pr.payee) != item.canary_snapshot:
                raise CanaryError("canary_commission_source_invalid")
        if item.source_type == Commission.Source.REVERSAL:
            original = Commission.objects.filter(external_id=item.source_external_id, canary_run_id=pr.canary_run_id, payee_id=pr.payee_id).first()
            if not original or item.amount != -original.amount:
                raise CanaryError("canary_reversal_invalid")
        elif not expected:
            raise CanaryError("canary_commission_source_invalid")
    profile = getattr(pr.payee, "profile", None)
    # The authorized canary recipient is the owner's CPF PIX, never an arbitrary override.
    if not profile or _digits(pr.pix_key) != _digits(profile.cpf) or len(_digits(pr.pix_key)) != 11:
        raise CanaryError("canary_pix_recipient_invalid")


def record_payout(pr):
    if not pr.canary_run_id:
        return
    from finance.interface import ledger
    ledger.record_transaction(kind=FinancialTransaction.Kind.COMMISSION_PAYOUT, amount=pr.amount,
        source_type=FinancialTransaction.SourceType.WEEKLY_CLOSING, source_external_id=pr.external_id,
        idempotency_key=f"canary-payout:{pr.external_id}", canary_run_id=pr.canary_run_id,
        description=f"Despesa de teste {pr.canary_run_id}; Pix confirmado {pr.asaas_payment_id}",
        entries=[{"account_code": ledger.ACCOUNT_LIABILITY_PROMOTER, "entry_type": "debit", "amount": pr.amount},
                 {"account_code": ledger.ACCOUNT_ASSET_ASAAS, "entry_type": "credit", "amount": pr.amount}])
