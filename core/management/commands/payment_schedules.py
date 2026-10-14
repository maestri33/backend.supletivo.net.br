"""Install the persistent minute schedule for inbound payment recovery."""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Install or update the every-minute durable payment recovery schedule."

    def handle(self, *args, **options):
        from django_q.models import Schedule

        row, _ = Schedule.objects.update_or_create(
            name="payment_event_recovery",
            defaults={
                "func": "integrations.bank.recovery.recover",
                "schedule_type": Schedule.MINUTES,
                "minutes": 1,
                "repeats": -1,
                "next_run": timezone.now(),
            },
        )
        self.stdout.write(f"Payment recovery schedule installed: {row.name}")
