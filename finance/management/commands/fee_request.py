"""Validação manual (§8): enfileira uma despesa (fee) pra pagamento via PIX QR code.

Uso:
  python manage.py fee_request --amount 1.00 --qr "<copia-e-cola>" --supplier "Wyden"
  python manage.py fee_request --amount 1.00 --qr "<copia-e-cola>" --at "2026-06-10 09:00"   # agendado

⚠️ Só ENFILEIRA. O PIX real sai quando o worker rodar (`commission_process` processa a fila inteira) —
DINHEIRO REAL. Rode o worker só com autorização do Victor.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from finance.interface.fees import request_fee_payment, schedule_fee_on_due_date

SP_TZ = ZoneInfo("America/Sao_Paulo")


class Command(BaseCommand):
    help = "Enfileira uma despesa (fee) pra pagamento via PIX QR code (imediato ou agendado)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            default=None,
            help="valor em reais (ex.: 1.00). Opcional com --at-due (usa o valor do QR).",
        )
        parser.add_argument(
            "--qr", required=True, help="payload copia-e-cola do PIX QR code"
        )
        parser.add_argument(
            "--supplier", default=None, help="nome do fornecedor (texto)"
        )
        parser.add_argument("--description", default=None)
        parser.add_argument(
            "--at",
            default=None,
            help="agendar p/ 'YYYY-MM-DD HH:MM' (America/Sao_Paulo); ausente = imediato",
        )
        parser.add_argument(
            "--at-due",
            action="store_true",
            help="agendar para a DATA DE VENCIMENTO lida do próprio QR (cobrança com vencimento)",
        )

    def handle(self, *args, **o):
        if o["at_due"] and o["at"]:
            raise CommandError("--at-due e --at são mutuamente exclusivos")

        if o["at_due"]:
            # vencimento lido do próprio QR; amount é opcional (usa o valor do QR se ausente).
            try:
                pr = schedule_fee_on_due_date(
                    qr_payload=o["qr"],
                    amount=o["amount"],
                    supplier_name=o["supplier"],
                    description=o["description"],
                )
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        else:
            if o["amount"] is None:
                raise CommandError("--amount é obrigatório (exceto com --at-due)")
            scheduled_for = None
            if o["at"]:
                try:
                    scheduled_for = datetime.strptime(
                        o["at"], "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=SP_TZ)
                except ValueError as exc:
                    raise CommandError(
                        f"data inválida: {o['at']} (use 'YYYY-MM-DD HH:MM')"
                    ) from exc
            pr = request_fee_payment(
                amount=o["amount"],
                qr_payload=o["qr"],
                supplier_name=o["supplier"],
                description=o["description"],
                scheduled_for=scheduled_for,
            )
        self.stdout.write(
            json.dumps(
                {
                    "external_reference": pr.external_reference,
                    "kind": pr.kind,
                    "method": pr.method,
                    "amount": str(pr.amount),
                    "status": pr.status,
                    "supplier_name": pr.supplier_name,
                    "scheduled_for": str(pr.scheduled_for)
                    if pr.scheduled_for
                    else None,
                    "next_attempt_at": str(pr.next_attempt_at),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
