"""Entrypoints finos chamados pelo Django-Q (Schedules criados por `finance_schedules`).

Nada de regra de negócio aqui — só delega pro `interface/`. Mantém os nomes estáveis pros Schedules
(`finance.tasks.weekly_closing` / `finance.tasks.process_payouts`).
"""

from finance.interface import commissions, payout


def weekly_closing():
    """Schedule semanal (sexta 18h): fecha a semana e cria as solicitações de pagamento."""
    return commissions.run_weekly_closing()


def process_payouts():
    """Schedule recorrente: envia/reconcilia as solicitações de pagamento."""
    return payout.process_payment_requests()
