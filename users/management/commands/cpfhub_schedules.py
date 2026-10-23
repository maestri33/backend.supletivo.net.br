from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = 'Ensure persistent CPFHub retry and failed-alert recovery schedule.'

    def handle(self, *args, **options):
        Schedule.objects.update_or_create(name='users.cpfhub.retry', defaults={
            'func': 'users.auth.tasks.retry_pending_lookups', 'schedule_type': Schedule.MINUTES,
            'minutes': 1, 'repeats': -1,
        })
        self.stdout.write('CPFHub recovery schedule configured (every minute).')
