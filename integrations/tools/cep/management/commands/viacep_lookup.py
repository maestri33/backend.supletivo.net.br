"""Validação manual da tool ViaCEP: faz uma chamada REAL e imprime o resultado.

Uso: python manage.py viacep_lookup 01001000
Serve pra fechar o Portão 3 (§8 — integração só liga ao resto após chamada real).
"""

import json

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.tools.cep.scripts import viacep


class Command(BaseCommand):
    help = "Consulta um CEP na ViaCEP e imprime os campos normalizados."

    def add_arguments(self, parser):
        parser.add_argument("cep", help="CEP a consultar (com ou sem hífen)")

    def handle(self, *args, **options):
        cep = options["cep"]
        try:
            result = async_to_sync(viacep.lookup)(cep)
        except viacep.ViaCepUnavailable as exc:
            self.stderr.write(self.style.ERROR(f"ViaCEP indisponível: {exc}"))
            return

        if result is None:
            self.stdout.write(
                self.style.WARNING(
                    f'CEP "{cep}" não encontrado ou com formato inválido.'
                )
            )
            return

        self.stdout.write(self.style.SUCCESS("CEP encontrado:"))
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
