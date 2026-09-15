"""Motor de Ledger (Partidas Dobradas), Previsibilidade e Resoluções Soberanas do Admin."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
import uuid
from zoneinfo import ZoneInfo

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from finance.interface.audit import log_financial_audit
from finance.models import (
    Commission,
    DisputeRecord,
    FinancialAccount,
    FinancialAuditLog,
    FinancialTransaction,
    LedgerEntry,
    PaymentRequest,
    UnexpectedExpense,
)

logger = structlog.get_logger()
SP_TZ = ZoneInfo("America/Sao_Paulo")

# Códigos padrão do plano de contas contábil
ACCOUNT_ASSET_ASAAS = "ASSET_ASAAS"
ACCOUNT_LIABILITY_PROMOTER = "LIABILITY_PROMOTER_PAYABLE"
ACCOUNT_LIABILITY_FEES = "LIABILITY_FEES_PAYABLE"
ACCOUNT_EQUITY_CAPITAL = "EQUITY_CAPITAL"
ACCOUNT_REVENUE_ENROLLMENT = "REVENUE_ENROLLMENT"
ACCOUNT_EXPENSE_COMMISSION = "EXPENSE_COMMISSION"
ACCOUNT_EXPENSE_FEES = "EXPENSE_FEES"
ACCOUNT_EXPENSE_UNEXPECTED = "EXPENSE_UNEXPECTED"
ACCOUNT_EXPENSE_DISPUTES = "EXPENSE_DISPUTES"
ACCOUNT_EXPENSE_OPERATIONAL = "EXPENSE_OPERATIONAL"

_DEFAULT_ACCOUNTS = [
    (ACCOUNT_ASSET_ASAAS, "Conta Corrente / Gateway Asaas", FinancialAccount.Category.ASSET),
    (ACCOUNT_LIABILITY_PROMOTER, "Comissões de Promotores a Pagar", FinancialAccount.Category.LIABILITY),
    (ACCOUNT_LIABILITY_FEES, "Taxas Institucionais a Pagar", FinancialAccount.Category.LIABILITY),
    (ACCOUNT_EQUITY_CAPITAL, "Capital Social / Ajustes de Patrimônio", FinancialAccount.Category.EQUITY),
    (ACCOUNT_REVENUE_ENROLLMENT, "Receita com Matrículas e Vendas", FinancialAccount.Category.REVENUE),
    (ACCOUNT_EXPENSE_COMMISSION, "Despesa com Comissões de Venda", FinancialAccount.Category.EXPENSE),
    (ACCOUNT_EXPENSE_FEES, "Despesa com Taxas de Credenciamento", FinancialAccount.Category.EXPENSE),
    (ACCOUNT_EXPENSE_UNEXPECTED, "Despesa com Custos Imprevistos / Emergenciais", FinancialAccount.Category.EXPENSE),
    (ACCOUNT_EXPENSE_DISPUTES, "Despesa com Perdas e Chargebacks", FinancialAccount.Category.EXPENSE),
    (ACCOUNT_EXPENSE_OPERATIONAL, "Despesas Operacionais Gerais", FinancialAccount.Category.EXPENSE),
]


def ensure_default_accounts() -> dict[str, FinancialAccount]:
    """Garante a existência das contas fundamentais do plano de contas contábil."""
    accounts = {}
    for code, name, category in _DEFAULT_ACCOUNTS:
        acc, _ = FinancialAccount.objects.get_or_create(
            code=code,
            defaults={"name": name, "category": category},
        )
        accounts[code] = acc
    return accounts


def record_transaction(
    *,
    kind: str,
    amount: Decimal | str,
    source_type: str,
    idempotency_key: str,
    source_external_id: uuid.UUID | str | None = None,
    description: str | None = None,
    entries: list[dict[str, Any]],
    settled: bool = True,
) -> FinancialTransaction:
    """Registra atomicamente uma transação financeira com partidas dobradas (Double-Entry).

    Invariante estrita: SUM(DEBIT) == SUM(CREDIT) == amount (positivo).
    Idempotência garantida pela `idempotency_key`.
    """
    if not (idempotency_key or "").strip():
        raise ValueError("idempotency_key_required")

    amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount_dec <= 0:
        raise ValueError("amount_must_be_positive")

    source_uuid = None
    if source_external_id:
        source_uuid = (
            uuid.UUID(str(source_external_id))
            if isinstance(source_external_id, str)
            else source_external_id
        )

    # Verifica idempotência
    existing = FinancialTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    # Validação do balanceamento de partidas dobradas
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for entry in entries:
        e_amount = Decimal(str(entry["amount"])).quantize(Decimal("0.01"))
        if e_amount <= 0:
            raise ValueError("entry_amount_must_be_positive")
        if entry["entry_type"] == LedgerEntry.EntryType.DEBIT:
            total_debit += e_amount
        elif entry["entry_type"] == LedgerEntry.EntryType.CREDIT:
            total_credit += e_amount
        else:
            raise ValueError(f"invalid_entry_type: {entry.get('entry_type')}")

    if total_debit != total_credit:
        raise ValueError(
            f"unbalanced_ledger: total_debit={total_debit} != total_credit={total_credit}"
        )

    accounts_map = ensure_default_accounts()

    with transaction.atomic():
        try:
            tx = FinancialTransaction.objects.create(
                kind=kind,
                amount=amount_dec,
                status=FinancialTransaction.Status.COMPLETED if settled else FinancialTransaction.Status.PENDING,
                description=description,
                source_type=source_type,
                source_external_id=source_uuid,
                idempotency_key=idempotency_key,
                settled_at=timezone.now() if settled else None,
            )
        except IntegrityError:
            # Tratamento de corrida de idempotência concorrente
            return FinancialTransaction.objects.get(idempotency_key=idempotency_key)

        for entry in entries:
            acc_code = entry["account_code"]
            account = accounts_map.get(acc_code) or FinancialAccount.objects.get(code=acc_code)
            e_amount = Decimal(str(entry["amount"])).quantize(Decimal("0.01"))
            LedgerEntry.objects.create(
                transaction=tx,
                account=account,
                entry_type=entry["entry_type"],
                amount=e_amount,
            )

    return tx


def create_manual_adjustment(
    *,
    actor,
    account_code: str,
    entry_type: str,
    amount: Decimal | str,
    justification: str,
    idempotency_key: str,
    counterpart_account_code: str | None = None,
    description: str | None = None,
) -> FinancialTransaction:
    """Realiza um ajuste manual contábil soberano executado pelo Admin.

    Exige justificativa obrigatória e gera registro imediato em FinancialAuditLog.
    """
    if not (justification or "").strip():
        raise ValueError("justification_required")

    amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount_dec <= 0:
        raise ValueError("amount_must_be_positive")

    # Define a contrapartida padrão se não fornecida
    if not counterpart_account_code:
        counterpart_account_code = (
            ACCOUNT_EQUITY_CAPITAL
            if account_code != ACCOUNT_EQUITY_CAPITAL
            else ACCOUNT_EXPENSE_OPERATIONAL
        )

    counterpart_type = (
        LedgerEntry.EntryType.CREDIT
        if entry_type == LedgerEntry.EntryType.DEBIT
        else LedgerEntry.EntryType.DEBIT
    )

    entries = [
        {"account_code": account_code, "entry_type": entry_type, "amount": amount_dec},
        {"account_code": counterpart_account_code, "entry_type": counterpart_type, "amount": amount_dec},
    ]

    with transaction.atomic():
        tx = record_transaction(
            kind=FinancialTransaction.Kind.MANUAL_ADJUSTMENT,
            amount=amount_dec,
            source_type=FinancialTransaction.SourceType.MANUAL_ADMIN,
            idempotency_key=idempotency_key,
            description=description or f"Ajuste Manual Admin: {justification}",
            entries=entries,
        )

        log_financial_audit(
            actor=actor,
            action=FinancialAuditLog.Action.MANUAL_ADJUSTMENT,
            target_model="FinancialTransaction",
            target_external_id=tx.external_id,
            justification=justification,
            snapshot_after={
                "transaction_external_id": str(tx.external_id),
                "account_code": account_code,
                "entry_type": entry_type,
                "amount": str(amount_dec),
                "counterpart": counterpart_account_code,
            },
        )

    return tx


def create_unexpected_expense(
    *,
    actor,
    category: str,
    amount: Decimal | str,
    description: str,
    justification: str,
    supplier_name: str | None = None,
    method: str = PaymentRequest.Method.PIX_KEY,
    pix_key: str | None = None,
    boleto_line: str | None = None,
    receipt_path: str | None = None,
    idempotency_key: str,
) -> tuple[UnexpectedExpense, PaymentRequest]:
    """Registra um custo imprevisto e cria a respectiva ordem de desembolso no gateway.

    O Admin tem poder total para liquidar custos emergenciais diretamente.
    """
    if not (justification or "").strip():
        raise ValueError("justification_required")
    if not (description or "").strip():
        raise ValueError("description_required")

    amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount_dec <= 0:
        raise ValueError("amount_must_be_positive")

    if method == PaymentRequest.Method.PIX_KEY and not (pix_key or "").strip():
        raise ValueError("pix_key_required")
    if method == PaymentRequest.Method.BOLETO and not (boleto_line or "").strip():
        raise ValueError("boleto_line_required")

    ext_ref = f"unexp_{idempotency_key.strip()}"

    entries = [
        {"account_code": ACCOUNT_EXPENSE_UNEXPECTED, "entry_type": LedgerEntry.EntryType.DEBIT, "amount": amount_dec},
        {"account_code": ACCOUNT_ASSET_ASAAS, "entry_type": LedgerEntry.EntryType.CREDIT, "amount": amount_dec},
    ]

    with transaction.atomic():
        # Cria ou recupera a transação mestre
        tx = record_transaction(
            kind=FinancialTransaction.Kind.UNEXPECTED_EXPENSE,
            amount=amount_dec,
            source_type=FinancialTransaction.SourceType.UNEXPECTED,
            idempotency_key=idempotency_key,
            description=f"Custo Imprevisto ({category}): {description}",
            entries=entries,
        )

        pr, pr_created = PaymentRequest.objects.get_or_create(
            external_reference=ext_ref,
            defaults={
                "kind": PaymentRequest.Kind.UNEXPECTED,
                "method": method,
                "amount": amount_dec,
                "supplier_name": supplier_name,
                "pix_key": pix_key,
                "boleto_line": boleto_line,
                "receipt": receipt_path,
                "source_type": PaymentRequest.SourceType.UNEXPECTED,
                "source_external_id": tx.external_id,
                "status": PaymentRequest.Status.QUEUED,
            },
        )

        ue, _ = UnexpectedExpense.objects.get_or_create(
            transaction=tx,
            defaults={
                "payment_request": pr,
                "category": category,
                "amount": amount_dec,
                "description": description,
                "justification": justification,
                "supplier_name": supplier_name,
                "receipt": receipt_path,
                "registered_by": actor,
            },
        )

        log_financial_audit(
            actor=actor,
            action=FinancialAuditLog.Action.UNEXPECTED_EXPENSE,
            target_model="UnexpectedExpense",
            target_external_id=ue.external_id,
            justification=justification,
            snapshot_after={
                "unexpected_expense_external_id": str(ue.external_id),
                "payment_request_external_id": str(pr.external_id),
                "category": category,
                "amount": str(amount_dec),
                "supplier_name": supplier_name,
                "method": method,
            },
        )

    return ue, pr


def resolve_dispute(
    *,
    actor,
    external_dispute_id: str,
    resolution: str,
    justification: str,
    correlated_commission_id: uuid.UUID | str | None = None,
) -> DisputeRecord:
    """Executa o veredito final e soberano do Admin sobre uma disputa / chargeback."""
    if not (justification or "").strip():
        raise ValueError("justification_required")

    dispute = DisputeRecord.objects.select_for_update().filter(
        external_dispute_id=external_dispute_id
    ).first()
    if not dispute:
        raise ValueError("dispute_not_found")

    snapshot_before = {
        "status": dispute.status,
        "resolution": dispute.resolution,
        "justification": dispute.justification,
    }

    with transaction.atomic():
        if resolution == DisputeRecord.Resolution.ABSORB_LOSS:
            dispute.status = DisputeRecord.Status.RESOLVED_ABSORBED
            # Lança perda operacional por chargeback
            record_transaction(
                kind=FinancialTransaction.Kind.CHARGEBACK,
                amount=dispute.amount,
                source_type=FinancialTransaction.SourceType.DISPUTE,
                idempotency_key=f"dispute_absorb_{dispute.external_dispute_id}",
                description=f"Perda absorvida de chargeback {dispute.external_dispute_id}",
                entries=[
                    {"account_code": ACCOUNT_EXPENSE_DISPUTES, "entry_type": LedgerEntry.EntryType.DEBIT, "amount": dispute.amount},
                    {"account_code": ACCOUNT_ASSET_ASAAS, "entry_type": LedgerEntry.EntryType.CREDIT, "amount": dispute.amount},
                ],
            )
        elif resolution == DisputeRecord.Resolution.DEBIT_PROMOTER:
            dispute.status = DisputeRecord.Status.RESOLVED_DEBITED
            # Se houver comissão relacionada pendente, cancela-a
            if correlated_commission_id:
                comm = Commission.objects.filter(external_id=correlated_commission_id).first()
                if comm and comm.status == Commission.Status.PENDING:
                    comm.status = Commission.Status.CANCELLED
                    comm.save(update_fields=["status", "updated_at"])
            # Lança cancelamento no passivo de comissões
            record_transaction(
                kind=FinancialTransaction.Kind.CHARGEBACK,
                amount=dispute.amount,
                source_type=FinancialTransaction.SourceType.DISPUTE,
                idempotency_key=f"dispute_debit_{dispute.external_dispute_id}",
                description=f"Chargeback estornado do promotor {dispute.external_dispute_id}",
                entries=[
                    {"account_code": ACCOUNT_LIABILITY_PROMOTER, "entry_type": LedgerEntry.EntryType.DEBIT, "amount": dispute.amount},
                    {"account_code": ACCOUNT_ASSET_ASAAS, "entry_type": LedgerEntry.EntryType.CREDIT, "amount": dispute.amount},
                ],
            )
        elif resolution == DisputeRecord.Resolution.CONTEST_GATEWAY:
            dispute.status = DisputeRecord.Status.RESOLVED_CONTESTED
        else:
            raise ValueError(f"invalid_resolution: {resolution}")

        dispute.resolution = resolution
        dispute.justification = justification.strip()
        dispute.resolved_by = actor
        dispute.resolved_at = timezone.now()
        dispute.save()

        log_financial_audit(
            actor=actor,
            action=FinancialAuditLog.Action.DISPUTE_RESOLUTION,
            target_model="DisputeRecord",
            target_external_id=dispute.external_id,
            justification=justification,
            snapshot_before=snapshot_before,
            snapshot_after={
                "status": dispute.status,
                "resolution": dispute.resolution,
                "resolved_at": dispute.resolved_at.isoformat(),
            },
        )

    return dispute


def get_cashflow_overview() -> dict[str, Any]:
    """Consolida os indicadores em tempo real para controle e previsibilidade financeira do Admin."""
    now = timezone.now().astimezone(SP_TZ)

    # 1. Total de saídas pendentes / em voo na fila
    pending_payouts_agg = PaymentRequest.objects.filter(
        status__in=[
            PaymentRequest.Status.QUEUED,
            PaymentRequest.Status.SUBMITTED,
            PaymentRequest.Status.AWAITING_BALANCE,
            PaymentRequest.Status.AWAITING_PIX,
        ]
    ).aggregate(total=Sum("amount"))
    pending_payouts_amount = pending_payouts_agg["total"] or Decimal("0.00")

    # 2. Comissões pendentes da semana (provisão flutuante)
    pending_commissions_agg = Commission.objects.filter(
        status=Commission.Status.PENDING
    ).aggregate(total=Sum("amount"))
    pending_commissions_amount = pending_commissions_agg["total"] or Decimal("0.00")

    # 3. Custos imprevistos do mês atual
    first_day_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_unexpected_agg = UnexpectedExpense.objects.filter(
        created_at__gte=first_day_month
    ).aggregate(total=Sum("amount"))
    month_unexpected_amount = month_unexpected_agg["total"] or Decimal("0.00")

    # 4. Disputas abertas / sob análise
    open_disputes_agg = DisputeRecord.objects.filter(
        status__in=[DisputeRecord.Status.OPEN, DisputeRecord.Status.UNDER_REVIEW]
    ).aggregate(total=Sum("amount"))
    open_disputes_amount = open_disputes_agg["total"] or Decimal("0.00")

    # 5. Total de receitas acumuladas no mês (via Ledger)
    revenue_month_agg = LedgerEntry.objects.filter(
        account__code=ACCOUNT_REVENUE_ENROLLMENT,
        entry_type=LedgerEntry.EntryType.CREDIT,
        created_at__gte=first_day_month,
    ).aggregate(total=Sum("amount"))
    revenue_month_amount = revenue_month_agg["total"] or Decimal("0.00")

    return {
        "pending_payouts_queue": str(pending_payouts_amount),
        "unclosed_commissions_liability": str(pending_commissions_amount),
        "month_unexpected_expenses": str(month_unexpected_amount),
        "open_disputes_at_risk": str(open_disputes_amount),
        "month_accumulated_revenue": str(revenue_month_amount),
        "total_obligations_due": str(pending_payouts_amount + pending_commissions_amount),
        "timestamp": now.isoformat(),
    }


def list_transactions(*, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Consulta 100% das transações mestres para o cockpit do Admin."""
    qs = FinancialTransaction.objects.order_by("-created_at")
    if kind:
        qs = qs.filter(kind=kind)

    results = []
    for tx in qs[:limit]:
        results.append(
            {
                "external_id": str(tx.external_id),
                "kind": tx.kind,
                "amount": str(tx.amount),
                "status": tx.status,
                "description": tx.description,
                "source_type": tx.source_type,
                "source_external_id": str(tx.source_external_id) if tx.source_external_id else None,
                "idempotency_key": tx.idempotency_key,
                "created_at": tx.created_at.isoformat(),
                "settled_at": tx.settled_at.isoformat() if tx.settled_at else None,
            }
        )
    return results


def list_ledger_entries(
    *,
    account_code: str | None = None,
    entry_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Consulta os lançamentos contábeis de partidas dobradas (visão contábil detalhada)."""
    qs = LedgerEntry.objects.select_related("account", "transaction").order_by("-created_at")
    if account_code:
        qs = qs.filter(account__code=account_code)
    if entry_type:
        qs = qs.filter(entry_type=entry_type)

    results = []
    for entry in qs[:limit]:
        results.append(
            {
                "external_id": str(entry.external_id),
                "transaction_external_id": str(entry.transaction.external_id),
                "account_code": entry.account.code,
                "account_name": entry.account.name,
                "entry_type": entry.entry_type,
                "amount": str(entry.amount),
                "balance_after": str(entry.balance_after) if entry.balance_after is not None else None,
                "created_at": entry.created_at.isoformat(),
            }
        )
    return results


def get_asaas_reconciliation_report() -> dict[str, Any]:
    """Cruza saldo real do Asaas, saldo do ativo contábil ASSET_ASAAS e obrigações pendentes.

    Retorna um dict compatível com AsaasReconciliationOut:
        - asaas_live_balance: saldo atual da conta Asaas (None se API indisponível)
        - ledger_asset_balance: saldo do ativo ASSET_ASAAS no ledger (débitos - créditos)
        - total_debits/credits: soma das entradas por tipo no ASSET_ASAAS
        - pending_payouts: soma das saídas pendentes/em fila
        - pending_commissions: soma das comissões provisórias não liquidadas
        - total_obligations: pending_payouts + pending_commissions
        - liquid_projected_balance: saldo ativo - total_obligations
        - is_solvent: True se liquid_projected_balance >= 0
        - reconciled_at: timestamp da conciliação
    """
    now = timezone.now().astimezone(SP_TZ)

    # 1. Saldo do ativo ASSET_ASAAS no ledger (débitos - créditos)
    asset_debits_agg = LedgerEntry.objects.filter(
        account__code=ACCOUNT_ASSET_ASAAS,
        entry_type=LedgerEntry.EntryType.DEBIT,
    ).aggregate(total=Sum("amount"))
    total_debits = asset_debits_agg["total"] or Decimal("0.00")

    asset_credits_agg = LedgerEntry.objects.filter(
        account__code=ACCOUNT_ASSET_ASAAS,
        entry_type=LedgerEntry.EntryType.CREDIT,
    ).aggregate(total=Sum("amount"))
    total_credits = asset_credits_agg["total"] or Decimal("0.00")

    ledger_asset_balance = total_debits - total_credits

    # 2. Obrigações pendentes
    pending_payouts_agg = PaymentRequest.objects.filter(
        status__in=[
            PaymentRequest.Status.QUEUED,
            PaymentRequest.Status.SUBMITTED,
            PaymentRequest.Status.AWAITING_BALANCE,
            PaymentRequest.Status.AWAITING_PIX,
        ]
    ).aggregate(total=Sum("amount"))
    pending_payouts = pending_payouts_agg["total"] or Decimal("0.00")

    pending_comm_agg = Commission.objects.filter(
        status=Commission.Status.PENDING
    ).aggregate(total=Sum("amount"))
    pending_commissions = pending_comm_agg["total"] or Decimal("0.00")

    total_obligations = pending_payouts + pending_commissions

    # 3. Saldo real Asaas (tenta buscar via API; None se API indisponível)
    asaas_live_balance = None
    try:
        from integrations.bank.asaas.onboarding import account_balance as _asaas_balance
        bal = _asaas_balance()
        asaas_live_balance = Decimal(str(bal.get("balance", 0))).quantize(Decimal("0.01"))
    except Exception:
        pass

    # 4. Liquidez projetada (saldo ativo - obrigações totais)
    if asaas_live_balance is not None:
        liquid_projected = asaas_live_balance - total_obligations
    else:
        liquid_projected = ledger_asset_balance - total_obligations

    is_solvent = liquid_projected >= Decimal("0.00")

    return {
        "asaas_live_balance": str(asaas_live_balance) if asaas_live_balance is not None else None,
        "ledger_asset_balance": str(ledger_asset_balance),
        "total_debits": str(total_debits),
        "total_credits": str(total_credits),
        "pending_payouts": str(pending_payouts),
        "pending_commissions": str(pending_commissions),
        "total_obligations": str(total_obligations),
        "liquid_projected_balance": str(liquid_projected),
        "is_solvent": is_solvent,
        "reconciled_at": now.isoformat(),
    }

