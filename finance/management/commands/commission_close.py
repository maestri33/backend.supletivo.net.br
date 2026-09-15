"""Validação manual (§8): roda o fechamento semanal (a "sexta 18h").

Uso:
  python manage.py commission_close                 # usa a semana de agora
  python manage.py commission_close --date 2026-06-05  # simula o fechamento daquela semana

Idempotente: re-rodar a mesma semana é no-op (external_reference já existe). Imprime o resumo
(bônus disparados, solicitações criadas, quantas ficaram sem chave PIX).
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from finance.interface.commissions import run_weekly_closing

SP_TZ = ZoneInfo("America/Sao_Paulo")


class Command(BaseCommand):
    help = "Roda o fechamento semanal de comissões (sexta 18h America/Sao_Paulo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            default=None,
            help="data ISO (YYYY-MM-DD) p/ simular a semana; default = agora",
        )

    def handle(self, *args, **o):
        reference = None
        if o["date"]:
            try:
                day = datetime.strptime(o["date"], "%Y-%m-%d")
            except ValueError as exc:
                raise CommandError(
                    f"data inválida: {o['date']} (use YYYY-MM-DD)"
                ) from exc
            # ancora ao meio-dia SP p/ evitar virada de dia por fuso.
            reference = day.replace(hour=12, tzinfo=SP_TZ)

        summary = run_weekly_closing(reference_date=reference)
        self.stdout.write(self.style.SUCCESS("fechamento concluído:"))
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
