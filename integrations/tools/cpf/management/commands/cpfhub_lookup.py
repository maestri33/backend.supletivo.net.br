"""Validação manual da tool CPFHub: faz uma chamada REAL e imprime o resultado.

Uso: python manage.py cpfhub_lookup 09126367939
Serve pra fechar o Portão 3 (§8 — integração só liga ao resto após chamada REAL com api-key real).
"""

import json

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.tools.cpf.scripts import cpfhub


class Command(BaseCommand):
    help = "Consulta um CPF na CPFHub e imprime a identidade normalizada."

    def add_arguments(self, parser):
        parser.add_argument("cpf", help="CPF a consultar (com ou sem formatação)")

    def handle(self, *args, **options):
        cpf = options["cpf"]
        try:
            result = async_to_sync(cpfhub.lookup)(cpf)
        except cpfhub.CpfHubError as exc:
            self.stderr.write(self.style.ERROR(f"CPFHub erro: {exc}"))
            return

        if result is None:
            self.stdout.write(
                self.style.WARNING(
                    f'CPF "{cpf}" não encontrado ou com formato inválido.'
                )
            )
            return

        self.stdout.write(self.style.SUCCESS("CPF encontrado:"))
        self.stdout.write(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
