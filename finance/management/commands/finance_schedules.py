"""Cria os Schedules do Django-Q do finance (idempotente — rodar 1×; não vai no ready()/boot).

- `finance.weekly_closing`: WEEKLY, próximo disparo = próxima sexta às `COMMISSION_CLOSING_HOUR`
  (default 18h) America/Sao_Paulo. WEEKLY re-soma 7 dias a cada run → cai sempre na mesma sexta/hora.
  (Usamos WEEKLY, não CRON, de propósito: o CRON do Django-Q exige `croniter`, que NÃO é dependência
  do projeto — não adiciono dep não pedida; a robustez vem da idempotência do fechamento.)
- `finance.process_payouts`: MINUTES a cada 1 min (envia/reconcilia a fila de payout).

Uso: python manage.py finance_schedules
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

from finance import config

SP_TZ = ZoneInfo("America/Sao_Paulo")


def _next_closing() -> datetime:
    """Próxima ocorrência do dia/hora de fechamento (default sexta 18h) em America/Sao_Paulo."""
    now = timezone.now().astimezone(SP_TZ)
    weekday = config.closing_weekday()  # 0=seg..4=sex
    hour = config.closing_hour()
    days_ahead = (weekday - now.weekday()) % 7
    candidate = datetime.combine(
        (now + timedelta(days=days_ahead)).date(), time(hour, 0), tzinfo=SP_TZ
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


class Command(BaseCommand):
    help = "Cria/garante os Schedules Django-Q do finance (fechamento semanal + worker de payout)."

    def handle(self, *args, **o):
        closing, created_closing = Schedule.objects.get_or_create(
            name="finance.weekly_closing",
            defaults={
                "func": "finance.tasks.weekly_closing",
                "schedule_type": Schedule.WEEKLY,
                "next_run": _next_closing(),
            },
        )
        worker, created_worker = Schedule.objects.get_or_create(
            name="finance.process_payouts",
            defaults={
                "func": "finance.tasks.process_payouts",
                "schedule_type": Schedule.MINUTES,
                "minutes": 1,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"weekly_closing: {'criado' if created_closing else 'já existia'} "
                f"(próximo: {closing.next_run:%Y-%m-%d %H:%M %Z}); "
                f"process_payouts: {'criado' if created_worker else 'já existia'} (a cada 1 min)."
            )
        )
