from django.core.management.base import BaseCommand
from django.utils import timezone

from users.auth.models import User


class Command(BaseCommand):
    help = "Remove usuários sintéticos cujo TTL expirou."

    def handle(self, *args, **options):
        expired = User.objects.filter(
            is_test=True,
            test_expires_at__isnull=False,
            test_expires_at__lte=timezone.now(),
        )
        count = expired.count()
        expired.delete()
        self.stdout.write(self.style.SUCCESS(f"removed={count}"))
