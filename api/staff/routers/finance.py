"""Router Financeiro e Payouts (Staff)."""

from __future__ import annotations

from decimal import Decimal
from ninja import File, Form, Header, Query, Router, Status
from ninja.errors import HttpError
from ninja.files import UploadedFile

from api.auth import require_superuser
from api.staff.schemas import (
    AdvancePayoutOut,
    AsaasReconciliationOut,
    CashflowOverviewOut,
    ClosingHealthOut,
    ClosingSimulationOut,
    DisputeRecordOut,
    DisputeResolveIn,
    FinanceAuditFilterSchema,
    FinanceBalanceOut,
    FinanceCommissionFilterSchema,
    FinanceLedgerFilterSchema,
    FinancePayoutFilterSchema,
    FinanceScheduleItemOut,
    FinanceScheduleRunOut,
    FinanceSummaryOut,
    FinanceTransactionFilterSchema,
    FinancialAuditLogOut,
    FinancialTransactionOut,
    LedgerEntryOut,
    ManualAdjustmentIn,
    ManualCommissionIn,
    ManualCommissionOut,
    ManualPaymentOut,
    PayoutOverridePixOut,
    PayoutRetryOut,
    StaffCommissionOut,
    StaffPaymentRequestOut,
    UnexpectedExpenseIn,
    UnexpectedExpenseOut,
    WeeklyClosingResultOut,
)
from finance import interface as finance_iface
from finance.interface import commissions as finance_closing
from finance.interface import ledger as finance_ledger
from finance.interface import manual as finance_manual
from finance.models import DisputeRecord
from integrations.bank.asaas import onboarding as asaas_onboarding
from users.exceptions import ValidationError


router = Router(tags=["staff"])

_MANUAL_PAYMENT_DETAIL = {
    "invalid_amount": "Valor inválido.",
    "amount_must_be_positive": "O valor deve ser positivo.",
    "pix_key_required": "Chave PIX obrigatória.",
    "line_code_required": "Linha digitável do boleto obrigatória.",
}


def _raise_manual_payment_error(exc: Exception):
    slug = str(exc)
    detail = _MANUAL_PAYMENT_DETAIL.get(slug, slug)
    raise ValidationError(detail, code=f"PAYMENT_{slug.upper()}") from exc


@router.get("/finance/balance", response=FinanceBalanceOut, summary="Saldo da conta Asaas")
def finance_balance(request):
    """Saldo da conta Asaas (read-only)."""
    require_superuser(request.auth)
    return asaas_onboarding.account_balance()


@router.get("/finance/summary", response=FinanceSummaryOut, summary="Resumo financeiro")
def finance_summary(request):
    """Resumo de comissões e fila de saída."""
    require_superuser(request.auth)
    return finance_iface.summary()


@router.get("/finance/commissions", response=list[StaffCommissionOut], summary="Listagem de comissões")
def finance_commissions(
    request,
    filters: FinanceCommissionFilterSchema = Query(default=None),
):
    """Comissões do sistema por status."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, FinanceCommissionFilterSchema) else FinanceCommissionFilterSchema()
    return finance_iface.list_commissions(status=f.status)


@router.post("/finance/commissions/manual", response={201: ManualCommissionOut}, summary="Creditar comissão avulsa / manual")
def create_manual_commission(request, payload: ManualCommissionIn):
    """Credita uma comissão manual / avulsa criada pelo Administrador para um colaborador."""
    require_superuser(request.auth)
    from users.auth.models import User

    user = User.objects.filter(external_id=payload.user_external_id).first()
    if user is None:
        raise ValidationError("Usuário beneficiário não encontrado.", code="USER_NOT_FOUND")

    try:
        c = finance_closing.credit_manual_commission(
            payee=user,
            amount=payload.amount,
            description=payload.description,
            role=payload.role,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), code="COMMISSION_INVALID") from exc

    return Status(201, {
        "external_id": str(c.external_id),
        "payee_external_id": str(user.external_id),
        "amount": str(c.amount),
        "source_type": c.source_type,
        "status": c.status,
        "created_at": c.created_at.isoformat(),
    })


@router.post("/finance/commissions/advance/{user_external_id}", response=AdvancePayoutOut, summary="Antecipar comissões e gerar payout imediato")
def advance_user_commissions(request, user_external_id: str):
    """Antecipa todas as comissões pendentes de um promotor/colaborador, enfileirando o pagamento imediatamente."""
    require_superuser(request.auth)
    from users.auth.models import User

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise ValidationError("Usuário não encontrado.", code="USER_NOT_FOUND")

    try:
        res = finance_closing.advance_user_payout(user=user)
        return res
    except ValueError as exc:
        raise ValidationError(str(exc), code="ADVANCE_PAYOUT_ERROR") from exc



@router.get("/finance/payouts", response=list[StaffPaymentRequestOut], summary="Solicitações de pagamento")
def finance_payouts(
    request,
    filters: FinancePayoutFilterSchema = Query(default=None),
):
    """Fila de solicitações de pagamento / payouts."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, FinancePayoutFilterSchema) else FinancePayoutFilterSchema()
    return finance_iface.list_payment_requests(status=f.status, kind=f.kind)


@router.post("/finance/payments", response={201: ManualPaymentOut}, summary="Pagamento avulso (PIX/Boleto)")
def create_manual_payment(
    request,
    kind: str = Form(...),
    amount: str | None = Form(None),
    description: str | None = Form(None),
    supplier_name: str | None = Form(None),
    pix_key: str | None = Form(None),
    boleto_line: str | None = Form(None),
    receipt: UploadedFile | None = File(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Enfileira pagamento avulso protegido por idempotência."""
    require_superuser(request.auth)
    if not (idempotency_key or "").strip():
        raise HttpError(422, "IDEMPOTENCY_KEY_REQUIRED")

    receipt_path = None
    if receipt is not None:
        from core.media import save_media

        ext = (getattr(receipt, "name", "") or "").rsplit(".", 1)[-1].lower() or "jpg"
        receipt_path = save_media(prefix="receipt", data=receipt.read(), ext=ext)

    try:
        if kind == "pix":
            pr = finance_manual.request_pix_payment(
                amount=amount,
                pix_key=pix_key,
                supplier_name=supplier_name,
                description=description,
                receipt=receipt_path,
                idempotency_key=idempotency_key,
            )
        elif kind == "boleto":
            pr = finance_manual.request_boleto_payment(
                line_code=boleto_line,
                amount=amount,
                supplier_name=supplier_name,
                description=description,
                receipt=receipt_path,
                idempotency_key=idempotency_key,
            )
        else:
            raise ValidationError(
                "kind deve ser 'pix' ou 'boleto'.", code="PAYMENT_INVALID_KIND"
            )
    except finance_manual.ManualPaymentError as exc:
        _raise_manual_payment_error(exc)
    return Status(201, {
        "external_id": str(pr.external_id),
        "kind": pr.kind,
        "method": pr.method,
        "amount": str(pr.amount),
        "status": pr.status,
        "external_reference": pr.external_reference,
        "receipt": pr.receipt,
    })


@router.post("/finance/closing/run", response=WeeklyClosingResultOut, summary="Executar fechamento semanal")
def run_closing(request):
    """Executa o fechamento semanal de comissões."""
    require_superuser(request.auth)
    return finance_closing.run_weekly_closing()


@router.get("/finance/closing/health", response=ClosingHealthOut, summary="Saúde do fechamento semanal")
def closing_health(request):
    """Cruza saldo do Asaas com obrigações pendentes."""
    require_superuser(request.auth)
    obligation = finance_iface.closing_obligation()
    estimated = Decimal(obligation["obrigacao_estimada"])

    balance = asaas_onboarding.account_balance()
    saldo = balance.get("balance") if isinstance(balance, dict) else None
    if saldo is None:
        return {
            **obligation,
            "saldo": None,
            "suficiente": None,
            "deficit": None,
            "balance_error": balance.get("error")
            if isinstance(balance, dict)
            else True,
        }
    saldo_dec = Decimal(str(saldo)).quantize(Decimal("0.01"))
    deficit = estimated - saldo_dec
    return {
        **obligation,
        "saldo": str(saldo_dec),
        "suficiente": saldo_dec >= estimated,
        "deficit": str(deficit) if deficit > 0 else "0.00",
    }


@router.get("/finance/closing/simulation", response=ClosingSimulationOut, summary="Simulação do fechamento semanal")
def closing_simulation(request):
    """Simula o fechamento semanal em memória com cálculo de bônus, beneficiários e pendências."""
    require_superuser(request.auth)
    return finance_closing.simulate_weekly_closing()


@router.post("/finance/payouts/{external_id}/retry", response=PayoutRetryOut, summary="Forçar retentativa de payout")
def retry_payout(request, external_id: str):
    """Força o reprocessamento imediato de uma solicitação de pagamento com erro ou sem saldo."""
    require_superuser(request.auth)
    from finance.interface import payout as finance_payout

    try:
        pr = finance_payout.retry_payment_request(external_id)
    except ValueError as exc:
        raise ValidationError(str(exc), code="PAYOUT_RETRY_ERROR") from exc

    return {
        "external_id": str(pr.external_id),
        "status": pr.status,
        "attempts": pr.attempts,
        "last_error": pr.last_error,
        "next_attempt_at": pr.next_attempt_at.isoformat() if pr.next_attempt_at else None,
    }


@router.post("/finance/payouts/{external_id}/override-pix", response=PayoutOverridePixOut, summary="Sobrescrever chave PIX e re-enfileirar")
def override_payout_pix(request, external_id: str, pix_key: str = Form(...), update_profile: bool = Form(True)):
    """Atualiza a chave PIX do payout (e opcionalmente do profile) e re-enfileira para pagamento."""
    require_superuser(request.auth)
    from finance.interface import payout as finance_payout

    try:
        pr = finance_payout.override_payment_request_pix(
            external_id=external_id, new_pix_key=pix_key, update_profile=update_profile
        )
    except ValueError as exc:
        raise ValidationError(str(exc), code="PAYOUT_PIX_OVERRIDE_ERROR") from exc

    return {
        "external_id": str(pr.external_id),
        "status": pr.status,
        "pix_key": pr.pix_key,
        "attempts": pr.attempts,
        "last_error": pr.last_error,
        "next_attempt_at": pr.next_attempt_at.isoformat() if pr.next_attempt_at else None,
    }


# ── Núcleo Contábil, Soberania e Previsibilidade Financeira ───────────────────


@router.get("/finance/ledger", response=list[LedgerEntryOut], summary="Extrato contábil irrestrito (Ledger)")
def get_ledger(
    request,
    filters: FinanceLedgerFilterSchema = Query(default=None),
):
    """Consulta os lançamentos contábeis de partidas dobradas (100% de visibilidade sem filtros ocultos)."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, FinanceLedgerFilterSchema) else FinanceLedgerFilterSchema()
    return finance_ledger.list_ledger_entries(
        account_code=f.account_code,
        entry_type=f.entry_type,
    )


@router.get("/finance/transactions", response=list[FinancialTransactionOut], summary="Visão 360° de transações financeiras")
def get_transactions(
    request,
    filters: FinanceTransactionFilterSchema = Query(default=None),
):
    """Listagem mestre de todas as transações financeiras do sistema."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, FinanceTransactionFilterSchema) else FinanceTransactionFilterSchema()
    return finance_ledger.list_transactions(kind=f.kind)


@router.get("/finance/cashflow", response=CashflowOverviewOut, summary="Cockpit de previsibilidade e fluxo de caixa")
def get_cashflow(request):
    """Consolida indicadores de caixa, saídas agendadas, provisões de comissão e riscos em tempo real."""
    require_superuser(request.auth)
    return finance_ledger.get_cashflow_overview()


@router.post("/finance/adjustments", response={201: FinancialTransactionOut}, summary="Ajuste manual contábil soberano")
def create_manual_adjustment(
    request,
    payload: ManualAdjustmentIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Lança ajuste manual contábil com justificativa obrigatória e registro imutável de auditoria."""
    admin_user = require_superuser(request.auth)
    if not (idempotency_key or "").strip():
        raise HttpError(422, "IDEMPOTENCY_KEY_REQUIRED")

    try:
        tx = finance_ledger.create_manual_adjustment(
            actor=admin_user,
            account_code=payload.account_code,
            entry_type=payload.entry_type,
            amount=payload.amount,
            justification=payload.justification,
            idempotency_key=idempotency_key,
            counterpart_account_code=payload.counterpart_account_code,
            description=payload.description,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), code="ADJUSTMENT_ERROR") from exc

    return Status(201, {
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
    })


@router.post("/finance/expenses/unexpected", response={201: UnexpectedExpenseOut}, summary="Pagar / Registrar custo imprevisto")
def create_unexpected_expense_endpoint(
    request,
    category: str = Form(...),
    amount: str = Form(...),
    description: str = Form(...),
    justification: str = Form(...),
    supplier_name: str | None = Form(None),
    method: str = Form("pix_key"),
    pix_key: str | None = Form(None),
    boleto_line: str | None = Form(None),
    receipt: UploadedFile | None = File(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Registra e emite ordem de desembolso para custos imprevistos ou emergenciais."""
    admin_user = require_superuser(request.auth)
    if not (idempotency_key or "").strip():
        raise HttpError(422, "IDEMPOTENCY_KEY_REQUIRED")

    receipt_path = None
    if receipt is not None:
        from core.media import save_media

        ext = (getattr(receipt, "name", "") or "").rsplit(".", 1)[-1].lower() or "jpg"
        receipt_path = save_media(prefix="receipt_unexpected", data=receipt.read(), ext=ext)

    try:
        ue, pr = finance_ledger.create_unexpected_expense(
            actor=admin_user,
            category=category,
            amount=amount,
            description=description,
            justification=justification,
            supplier_name=supplier_name,
            method=method,
            pix_key=pix_key,
            boleto_line=boleto_line,
            receipt_path=receipt_path,
            idempotency_key=idempotency_key,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), code="UNEXPECTED_EXPENSE_ERROR") from exc

    return Status(201, {
        "external_id": str(ue.external_id),
        "transaction_external_id": str(ue.transaction.external_id) if ue.transaction else None,
        "payment_request_external_id": str(pr.external_id) if pr else None,
        "category": ue.category,
        "amount": str(ue.amount),
        "description": ue.description,
        "justification": ue.justification,
        "supplier_name": ue.supplier_name,
        "receipt": ue.receipt,
        "created_at": ue.created_at.isoformat(),
    })


@router.get("/finance/disputes", response=list[DisputeRecordOut], summary="Listar disputas e chargebacks")
def list_disputes(request):
    """Consulta todas as disputas e contestações bancárias pendentes ou resolvidas."""
    require_superuser(request.auth)
    disputes = DisputeRecord.objects.order_by("-created_at")[:100]
    return [
        {
            "external_id": str(d.external_id),
            "external_dispute_id": d.external_dispute_id,
            "amount": str(d.amount),
            "status": d.status,
            "reason": d.reason,
            "resolution": d.resolution,
            "justification": d.justification,
            "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            "created_at": d.created_at.isoformat(),
        }
        for d in disputes
    ]


@router.post("/finance/disputes/{external_dispute_id}/resolve", response=DisputeRecordOut, summary="Veredito soberano de disputa / chargeback")
def resolve_dispute_endpoint(
    request,
    external_dispute_id: str,
    payload: DisputeResolveIn,
):
    """Aplica a decisão final soberana do Admin sobre uma contestação (absorver, debitar promotor ou contestar)."""
    admin_user = require_superuser(request.auth)
    try:
        dispute = finance_ledger.resolve_dispute(
            actor=admin_user,
            external_dispute_id=external_dispute_id,
            resolution=payload.resolution,
            justification=payload.justification,
            correlated_commission_id=payload.correlated_commission_id,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), code="DISPUTE_RESOLVE_ERROR") from exc

    return {
        "external_id": str(dispute.external_id),
        "external_dispute_id": dispute.external_dispute_id,
        "amount": str(dispute.amount),
        "status": dispute.status,
        "reason": dispute.reason,
        "resolution": dispute.resolution,
        "justification": dispute.justification,
        "resolved_at": dispute.resolved_at.isoformat() if dispute.resolved_at else None,
        "created_at": dispute.created_at.isoformat(),
    }



@router.get("/finance/audit", response=list[FinancialAuditLogOut], summary="Trilha de auditoria das intervenções financeiras do Admin")
def get_financial_audit(
    request,
    filters: FinanceAuditFilterSchema = Query(default=None),
):
    """Consulta o histórico completo e imutável de todas as decisões tomadas pelo Admin."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, FinanceAuditFilterSchema) else FinanceAuditFilterSchema()
    return finance_iface.list_financial_audit_logs(
        action=f.action,
        target_model=f.target_model,
    )


@router.get(
    "/finance/reconciliation",
    response={200: AsaasReconciliationOut},
    summary="Conciliação bancária Asaas vs Ledger",
)
def get_asaas_reconciliation(request):
    """Cruza saldo real do Asaas com o ativo contábil ASSET_ASAAS e as obrigações pendentes."""
    require_superuser(request.auth)
    return finance_ledger.get_asaas_reconciliation_report()


@router.get("/finance/schedules", response=list[FinanceScheduleItemOut], summary="Listar schedules e cronjobs do financeiro")
def list_finance_schedules(request):
    """Lista todos os schedules de fechamento e payouts cadastrados no Django-Q, com status da última execução."""
    require_superuser(request.auth)
    from django_q.models import Failure, Schedule, Success

    # Garante que os schedules de finance existam se ainda não tiverem sido criados
    if not Schedule.objects.filter(name__startswith="finance.").exists():
        from django.core.management import call_command
        try:
            call_command("finance_schedules")
        except Exception:
            pass

    schedules = list(Schedule.objects.all().order_by("name"))
    items = []
    for s in schedules:
        last_succ = Success.objects.filter(func=s.func).order_by("-stopped").first()
        last_fail = Failure.objects.filter(func=s.func).order_by("-stopped").first()

        last_run = None
        last_status = "never_run"
        last_result = None

        if last_succ and last_fail:
            if last_succ.stopped >= last_fail.stopped:
                last_run = last_succ.stopped
                last_status = "success"
                last_result = last_succ.result
            else:
                last_run = last_fail.stopped
                last_status = "failure"
                last_result = last_fail.result
        elif last_succ:
            last_run = last_succ.stopped
            last_status = "success"
            last_result = last_succ.result
        elif last_fail:
            last_run = last_fail.stopped
            last_status = "failure"
            last_result = last_fail.result

        items.append({
            "id": s.id,
            "name": s.name or s.func,
            "func": s.func,
            "schedule_type": s.schedule_type,
            "minutes": s.minutes,
            "repeats": s.repeats,
            "next_run": s.next_run,
            "last_run": last_run,
            "last_status": last_status,
            "last_result": last_result,
            "is_active": (s.repeats != 0),
        })

    return items


@router.post("/finance/schedules/{name}/run", response=FinanceScheduleRunOut, summary="Disparar execução imediata de um schedule")
def run_finance_schedule(request, name: str):
    """Executa imediatamente um schedule pelo nome ou função (útil para testes e fechamento manual)."""
    require_superuser(request.auth)
    import importlib
    from django.utils import timezone
    from django_q.models import Schedule

    # 1. Procura schedule pelo nome, func ou ID
    schedule = Schedule.objects.filter(name=name).first()
    if not schedule:
        schedule = Schedule.objects.filter(func=name).first()
    if not schedule and name.isdigit():
        schedule = Schedule.objects.filter(id=int(name)).first()

    func_path = schedule.func if schedule else name
    if func_path in ("weekly_closing", "finance.weekly_closing"):
        func_path = "finance.tasks.weekly_closing"
    elif func_path in ("process_payouts", "finance.process_payouts"):
        func_path = "finance.tasks.process_payouts"

    if "." not in func_path:
        raise ValidationError(f"Schedule '{name}' não encontrado e não é um caminho de função válido.", code="SCHEDULE_NOT_FOUND")

    try:
        mod_name, fn_name = func_path.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, fn_name)
        result = fn()
    except Exception as exc:
        raise ValidationError(f"Falha ao executar schedule '{name}': {exc}", code="SCHEDULE_RUN_FAILED") from exc

    return {
        "success": True,
        "schedule_name": schedule.name if schedule else name,
        "func": func_path,
        "result": result,
        "executed_at": timezone.now(),
    }
