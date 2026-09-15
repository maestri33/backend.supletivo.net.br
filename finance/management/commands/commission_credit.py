"""Validação manual (§8): credita uma comissão REAL (valor do .env) a um beneficiário.

Uso:
  python manage.py commission_credit --payee <external_id> --role promoter --source lead
  python manage.py commission_credit --payee <external_id> --role coordinator --source veteran \
      --source-id <uuid-do-student>

`--payee` = external_id (UUID) de um User com profile. Sem `--source-id`, gera um UUID novo (simula
um lead/student distinto). Idempotente: o mesmo (source, source-id) devolve a comissão já existente.
"""

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from finance.interface.commissions import credit_commission
from finance.models import Commission
from users.profiles.interface import find_by_external_id


class Command(BaseCommand):
    help = "Credita uma comissão (valor do .env) a um beneficiário pelo external_id."

    def add_arguments(self, parser):
        parser.add_argument(
            "--payee", required=True, help="external_id (UUID) do beneficiário"
        )
        parser.add_argument(
            "--role",
            required=True,
            choices=[Commission.Role.PROMOTER, Commission.Role.COORDINATOR],
            help="promoter | coordinator",
        )
        parser.add_argument(
            "--source",
            required=True,
            choices=[Commission.Source.LEAD, Commission.Source.VETERAN],
            help="lead (→promotor) | veteran (→coordenador)",
        )
        parser.add_argument(
            "--source-id",
            default=None,
            help="external_id do lead/student que disparou (default: UUID novo)",
        )

    def handle(self, *args, **o):
        source_id = o["source_id"] or str(uuid.uuid4())
        # borda da CLI: resolve o external_id → User (o oficial é o do User) antes de chamar o finance.
        profile = find_by_external_id(o["payee"])
        if profile is None:
            raise CommandError(f"payee_not_found: {o['payee']}")
        try:
            commission = credit_commission(
                payee=profile.user,
                payee_role=o["role"],
                source_type=o["source"],
                source_external_id=source_id,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            json.dumps(
                {
                    "external_id": str(commission.external_id),
                    "payee_role": commission.payee_role,
                    "source_type": commission.source_type,
                    "source_external_id": str(commission.source_external_id),
                    "amount": str(commission.amount),
                    "status": commission.status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
