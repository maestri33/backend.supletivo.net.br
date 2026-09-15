"""Validação manual (§8): roda uma passada do worker de payout (envia/reconcilia).

Uso:
  python manage.py commission_process            # uma passada
  python manage.py commission_process --loop 5   # 5 passadas (intervalo de reconciliação no teste)

⚠️ DINHEIRO REAL: este comando dispara o PIX-out de verdade pelas PaymentRequest na fila. Rode só
com autorização do Victor (valores mini no dev). Imprime o estado de cada PaymentRequest após a(s)
passada(s).
"""

import json

from django.core.management.base import BaseCommand

from finance.interface.payout import process_payment_requests
from finance.models import PaymentRequest


class Command(BaseCommand):
    help = "Processa as PaymentRequest na fila (envia PIX real via asaas + reconcilia)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop", type=int, default=1, help="quantas passadas rodar (default 1)"
        )

    def handle(self, *args, **o):
        for i in range(max(1, o["loop"])):
            summary = process_payment_requests()
            self.stdout.write(self.style.SUCCESS(f"passada {i + 1}: {summary}"))

        rows = [
            {
                "external_reference": pr.external_reference,
                "amount": str(pr.amount),
                "status": pr.status,
                "asaas_status": pr.asaas_status,
                "asaas_payment_id": pr.asaas_payment_id,
                "attempts": pr.attempts,
                "last_error": pr.last_error,
            }
            for pr in PaymentRequest.objects.order_by("-created_at")[:20]
        ]
        self.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2))
