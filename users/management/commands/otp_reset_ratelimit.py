"""Reseta o rate-limit de OTP de um usuário (por phone, cpf ou external_id).

Uso:
  manage.py otp_reset_ratelimit --phone 5542999384069
  manage.py otp_reset_ratelimit --cpf 07461638947
  manage.py otp_reset_ratelimit --external-id fac8b8d9-abe4-42f5-8dc1-cc64e2cc03fc
"""

from django.core.management.base import BaseCommand, CommandError

from users.auth.otp.models import OtpRateLimit
from users.auth.validation import validate_phone
from users.models import User
from users.profiles import interface as profiles


class Command(BaseCommand):
    help = "Reseta o rate-limit de OTP de um usuário (phone / cpf / external-id)."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--phone", help="Telefone do usuário")
        group.add_argument("--cpf", help="CPF do usuário")
        group.add_argument("--external-id", dest="external_id", help="UUID do usuário")

    def handle(self, *args, **o):
        user = self._find_user(o)
        deleted, _ = OtpRateLimit.objects.filter(user=user).delete()
        if deleted:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rate-limit resetado para {user.external_id} ({deleted} registro(s) removido(s))."
                )
            )
        else:
            self.stdout.write(f"Nenhum rate-limit encontrado para {user.external_id}.")

    def _find_user(self, o) -> User:
        if o["external_id"]:
            user = User.objects.filter(external_id=o["external_id"]).first()
            if not user:
                raise CommandError(f"Usuário não encontrado: {o['external_id']}")
            return user

        if o["cpf"]:
            profile = profiles.find_by_cpf(o["cpf"])
        else:
            try:
                phone = validate_phone(o["phone"])
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            profile = profiles.find_by_phone(phone)

        if not profile:
            raise CommandError("Usuário não encontrado.")
        return profile.user
