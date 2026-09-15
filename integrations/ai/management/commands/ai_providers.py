"""Valida cada provider de IA habilitado (§8): GET /models REAL com a key real → lista os modelos.

Prova que a credencial de cada provider funciona, sem gastar tokens de geração. Uso:
`python manage.py ai_providers`.
"""

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand

from integrations.ai import providers
from integrations.ai.client import LLMError


class Command(BaseCommand):
    help = "Valida cada provider de IA (GET /models real) e lista alguns modelos — prova a key (§8)."

    def handle(self, *args, **options):
        names = providers.enabled_providers()
        if not names:
            self.stderr.write(
                self.style.ERROR("Nenhum provider habilitado (IA_PROVIDERS vazio).")
            )
            return
        for name in names:
            client = providers.get_client(name)
            try:
                models = async_to_sync(client.list_models)()
            except LLMError as exc:
                self.stdout.write(self.style.ERROR(f"[{name}] FAIL: {exc}"))
                continue
            except Exception as exc:  # noqa: BLE001 — diagnóstico: reporta qualquer falha por provider
                self.stdout.write(
                    self.style.ERROR(f"[{name}] FAIL ({type(exc).__name__}): {exc}")
                )
                continue
            sample = ", ".join(models[:10]) if models else "(lista vazia)"
            self.stdout.write(
                self.style.SUCCESS(f"[{name}] OK — {len(models)} modelos. ex: {sample}")
            )
