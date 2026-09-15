from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from hub.models import Hub
from users.address import interface as address_iface
from users.auth.models import User
from users.profiles import interface as profiles
from users.profiles.models import Profile
from users.roles.candidate.models import Candidate
from users.roles.models import UserRole


class Command(BaseCommand):
    help = "Reseta e cria um candidato sintético para E2E em ambientes não produtivos."

    def handle(self, *args, **options):
        if settings.APP_ENV == "prod" or not settings.TEST_MODE:
            raise CommandError("seed_test_collaborator é proibido em APP_ENV=prod.")

        hub = Hub.objects.filter(is_default=True).first()
        if hub is None:
            raise CommandError(
                "Rode seed_defaults antes: o hub padrão ainda não existe."
            )

        phone = settings.TEST_COLLABORATOR_PHONE
        existing = Profile.objects.filter(phone=phone).select_related("user").first()
        if existing is not None and not existing.user.is_test:
            raise CommandError("TEST_COLLABORATOR_PHONE já pertence a uma conta real.")

        expires_at = timezone.now() + timedelta(hours=settings.TEST_DATA_TTL_HOURS)
        with transaction.atomic():
            if existing is not None:
                existing.user.delete()
            user = User.objects.create_user(is_test=True, test_expires_at=expires_at)
            profile = profiles.create(
                user=user,
                cpf=settings.TEST_COLLABORATOR_CPF,
                phone=phone,
                email=settings.TEST_COLLABORATOR_EMAIL,
                name="Promotor E2E V7M",
            )
            profiles.attach_address(profile, address_iface.create_empty())
            UserRole.objects.create(user=user, role="candidate")
            Candidate.objects.create(
                user=user, hub=hub, status=Candidate.Status.STARTED
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"test collaborator external_id={user.external_id} phone={phone} "
                f"otp={settings.TEST_MODE_OTP_CODE} expires_at={expires_at.isoformat()}"
            )
        )
