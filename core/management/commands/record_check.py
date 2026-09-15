"""Carimba um teste/validação no registro (core.ValidationCheck).

Uso (qualquer teste que a gente rodar deixa um rastro):
    manage.py record_check asaas webhook_external --passed --mode artificial \
        --detail "POST externo via exit-node chegou (WebhookEvent id=4)"
    manage.py record_check asaas algum_check --failed --detail "deu X"

Sem --passed nem --failed → assume passou (a maioria dos registros é sucesso).
"""

from django.core.management.base import BaseCommand

from core.validation import record_check


class Command(BaseCommand):
    help = "Grava um resultado de teste/validação em core.ValidationCheck (flag + horário)."

    def add_arguments(self, parser):
        parser.add_argument("scope", help="ex.: asaas")
        parser.add_argument("name", help="ex.: webhook_external")
        parser.add_argument(
            "--passed", action="store_true", help="marca como passou (default)"
        )
        parser.add_argument("--failed", action="store_true", help="marca como falhou")
        parser.add_argument("--mode", default="", help="artificial | real | link | ...")
        parser.add_argument(
            "--detail", default="", help="o que foi testado / evidência"
        )

    def handle(self, *args, **opts):
        passed = not opts["failed"]  # só falha se --failed for passado explicitamente
        row = record_check(
            opts["scope"],
            opts["name"],
            passed,
            mode=opts["mode"],
            detail=opts["detail"],
        )
        self.stdout.write(self.style.SUCCESS(f"registrado: {row}"))
