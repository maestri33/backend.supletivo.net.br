"""Comando administrativo de gestão do Canário de Produção (finance.canary).

Uso:
  python manage.py canary_run status
  python manage.py canary_run configure --actor-cpf 12345678901 --owner-cpf 11144477735 --student-cpf 52998224725 --student-phone 42998222222 --ttl 6 --justification "Homologação Canário Real"
  python manage.py canary_run disable --actor-cpf 12345678901 --justification "Encerramento do teste"
"""

from __future__ import annotations

import json
from django.core.management.base import BaseCommand, CommandError
from core.models import PlatformSetting
from finance import canary
from users.auth.models import User
from users.profiles.models import Profile


class Command(BaseCommand):
    help = "Gerencia o ciclo de vida do Canário de Produção isolado (finance.canary)."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action", required=True)

        # Status
        subparsers.add_parser("status", help="Exibe o estado atual da configuração do canário.")

        # Configure
        conf_parser = subparsers.add_parser("configure", help="Configura e ativa uma execução de canário.")
        conf_parser.add_argument("--actor-cpf", required=True, help="CPF do usuário Staff autorizador.")
        conf_parser.add_argument("--owner-cpf", required=True, help="CPF do Promotor titular da comissão.")
        conf_parser.add_argument("--student-cpf", required=True, help="CPF do Aluno testador.")
        conf_parser.add_argument("--student-phone", required=True, help="Telefone celular do Aluno testador.")
        conf_parser.add_argument("--ttl", type=int, default=24, help="Duração do canário em horas (1 a 72).")
        conf_parser.add_argument("--justification", required=True, help="Justificativa auditável.")

        # Disable
        dis_parser = subparsers.add_parser("disable", help="Desativa o canário ativo.")
        dis_parser.add_argument("--actor-cpf", required=True, help="CPF do usuário Staff autorizador.")
        dis_parser.add_argument("--justification", required=True, help="Justificativa auditável.")

    def handle(self, *args, **options):
        action = options["action"]

        if action == "status":
            self._handle_status()
        elif action == "configure":
            self._handle_configure(options)
        elif action == "disable":
            self._handle_disable(options)

    def _handle_status(self):
        row = PlatformSetting.objects.filter(key=canary.CONFIG_KEY).first()
        if not row:
            self.stdout.write(self.style.WARNING("Nenhum canário configurado (chave ausente)."))
            return

        try:
            val = json.loads(row.value)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Erro ao decodificar configuração: {exc}"))
            return

        active = val.get("active", False)
        status_str = self.style.SUCCESS("ATIVO") if active else self.style.WARNING("INATIVO")
        self.stdout.write(f"Estado do Canário: {status_str}")
        self.stdout.write(f"Run ID: {val.get('run_id')}")
        self.stdout.write(f"Emitido em: {val.get('issued_at')}")
        self.stdout.write(f"Expira em: {val.get('expires_at')}")
        self.stdout.write(f"Propostas emitidas: {val.get('proposal_count', 0)} / {canary.RULES['max_paid_sources']}")
        self.stdout.write(f"Promotor (Owner External ID): {val.get('owner_external_id')}")
        self.stdout.write("Allowlist de identidades:")
        for item in val.get("allowlist", []):
            cpf_masked = item.get("cpf", "")[:3] + ".***.***-" + item.get("cpf", "")[-2:]
            self.stdout.write(f"  - CPF: {cpf_masked} | Telefone: {item.get('phone')}")

    def _handle_configure(self, opts):
        actor_profile = Profile.objects.filter(cpf=canary._digits(opts["actor_cpf"])).select_related("user").first()
        if not actor_profile or not actor_profile.user.is_staff or not actor_profile.user.is_active:
            raise CommandError("Staff autorizador inválido, inativo ou não encontrado.")

        owner_profile = Profile.objects.filter(cpf=canary._digits(opts["owner_cpf"])).select_related("user").first()
        if not owner_profile or not owner_profile.user.is_active:
            raise CommandError("Promotor titular inválido, inativo ou não encontrado.")

        allowlist = [
            {"cpf": opts["owner_cpf"], "phone": owner_profile.phone},
            {"cpf": opts["student_cpf"], "phone": opts["student_phone"]},
        ]

        try:
            result = canary.configure(
                actor=actor_profile.user,
                owner=owner_profile.user,
                allowlist=allowlist,
                ttl_hours=opts["ttl"],
                justification=opts["justification"],
            )
            self.stdout.write(self.style.SUCCESS(f"Canário configurado com sucesso! Run ID: {result['run_id']}"))
            self.stdout.write(f"Expira em: {result['expires_at']}")
        except canary.CanaryError as exc:
            raise CommandError(f"Erro ao configurar canário: {exc}")

    def _handle_disable(self, opts):
        actor_profile = Profile.objects.filter(cpf=canary._digits(opts["actor_cpf"])).select_related("user").first()
        if not actor_profile or not actor_profile.user.is_staff or not actor_profile.user.is_active:
            raise CommandError("Staff autorizador inválido, inativo ou não encontrado.")

        try:
            run_id = canary.disable(actor=actor_profile.user, justification=opts["justification"])
            if run_id:
                self.stdout.write(self.style.SUCCESS(f"Canário {run_id} desativado com sucesso."))
            else:
                self.stdout.write(self.style.WARNING("Nenhum canário estava ativo."))
        except canary.CanaryError as exc:
            raise CommandError(f"Erro ao desativar canário: {exc}")
