"""Comando Django para sincronizar segredos do Infisical para a plataforma."""

from django.core.management.base import BaseCommand

from integrations.infisical.client import InfisicalClient
from integrations.infisical.sync import sync_secrets_to_platform


class Command(BaseCommand):
    help = "Sincroniza segredos do cofre Infisical para a tabela PlatformSetting e cache em memória."

    def add_arguments(self, parser):
        parser.add_argument(
            "--env",
            dest="environment",
            default=None,
            help="Ambiente de segredos no Infisical (ex: dev, prod, staging).",
        )
        parser.add_argument(
            "--base-url",
            dest="base_url",
            default=None,
            help="URL base do servidor Infisical (padrão: http://10.0.1.61:8080).",
        )
        parser.add_argument(
            "--project-id",
            dest="project_id",
            default=None,
            help="ID do Projeto no Infisical.",
        )
        parser.add_argument(
            "--client-id",
            dest="client_id",
            default=None,
            help="Client ID de Universal Auth.",
        )
        parser.add_argument(
            "--client-secret",
            dest="client_secret",
            default=None,
            help="Client Secret de Universal Auth.",
        )
        parser.add_argument(
            "--token",
            dest="token",
            default=None,
            help="Token de acesso direto do Infisical.",
        )

    def handle(self, *args, **options):
        env = options.get("environment")
        self.stdout.write(f"Iniciando sincronização de segredos do Infisical (env: {env or 'padrão'})...")

        client = InfisicalClient(
            base_url=options.get("base_url"),
            project_id=options.get("project_id"),
            client_id=options.get("client_id"),
            client_secret=options.get("client_secret"),
            token=options.get("token"),
            environment=env,
        )

        res = sync_secrets_to_platform(environment=env, client=client)

        if res.get("status") == "ok":
            synced_count = res.get("synced_count", 0)
            keys = res.get("keys", [])
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Sincronização concluída com sucesso: {synced_count} segredos atualizados."
                )
            )
            if keys:
                self.stdout.write(f"Chaves sincronizadas: {', '.join(keys)}")
        else:
            err = res.get("error", "Erro desconhecido")
            self.stdout.write(
                self.style.ERROR(
                    f"✗ Falha ao sincronizar com Infisical: {err}"
                )
            )
