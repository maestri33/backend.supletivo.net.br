"""Teste real do engine (Portão 3): chama generate_json caminhando a cadeia de fallback.

Faz UMA geração de verdade (gasta centavos). Mostra o resultado + as últimas linhas AiCall (numa
queda de provider aparecem a(s) tentativa(s) com erro + a que deu certo). Uso:
`python manage.py ai_ping` (ou `--model X` p/ fixar um modelo da cadeia).
"""

from django.core.management.base import BaseCommand

from integrations.ai import service
from integrations.ai.client import LLMError
from integrations.ai.models import AiCall


class Command(BaseCommand):
    help = "Chama a IA de verdade (generate_json) pela cadeia de fallback; mostra resultado + AiCall."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model", default=None, help="fixar um model presente na cadeia"
        )

    def handle(self, *args, **options):
        try:
            data = service.generate_json(
                "Liste 3 cidades do Rio Grande do Sul.",
                schema_description="Objeto JSON com a chave `cidades`: array de strings.",
                caller="ai_ping",
                model=options.get("model"),
            )
            self.stdout.write(self.style.SUCCESS(f"IA retornou: {data}"))
        except LLMError as exc:
            self.stderr.write(self.style.ERROR(f"IA falhou: {exc}"))
        self._dump_recent()

    def _dump_recent(self):
        recent = list(AiCall.objects.order_by("-created_at")[:6])[::-1]
        for call in recent:
            self.stdout.write(
                f"AiCall #{call.pk}: provider={call.provider} op={call.operation} "
                f"model={call.model} status={call.status} caller={call.caller} "
                f"prompt_tokens={call.prompt_tokens} completion_tokens={call.completion_tokens} "
                f"latency_ms={call.latency_ms} cost={call.cost} err={(call.error or '')[:60]}"
            )
