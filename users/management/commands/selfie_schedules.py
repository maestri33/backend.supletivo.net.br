"""Cria os Schedules do Django-Q que envelhecem selfies `pending` estouradas (idempotente — rodar 1×).

Antes, o `GET /candidate/selfie` e o `GET /enrollment/selfie` aplicavam o TTL NA LEITURA: uma selfie
`pending` cujo prazo estourou virava `review` + notificava o coordenador DENTRO do GET — um retry do
front, um preflight ou um crawler disparava a transição (viola idempotência/safety HTTP). A transição
foi movida pra estes jobs; os GETs viraram leitura pura.

- `users.age_stale_candidate_selfies`: MINUTES a cada 5 min.
- `users.age_stale_enrollment_selfies`: MINUTES a cada 5 min.

Intervalo curto (o TTL default é 120s): a selfie estourada cai na fila do coordenador em ≤5 min.

Uso (DEPLOY precisa rodar 1×): python manage.py selfie_schedules
"""

from django.core.management.base import BaseCommand
from django_q.models import Schedule

_SCHEDULES = (
    (
        "users.age_stale_candidate_selfies",
        "users.roles.candidate.tasks.age_stale_selfies",
    ),
    (
        "users.age_stale_enrollment_selfies",
        "users.roles.enrollment.tasks.age_stale_selfies",
    ),
)


class Command(BaseCommand):
    help = "Cria/garante os Schedules Django-Q que envelhecem selfies pending estouradas (TTL)."

    def handle(self, *args, **o):
        for name, func in _SCHEDULES:
            _, created = Schedule.objects.get_or_create(
                name=name,
                defaults={
                    "func": func,
                    "schedule_type": Schedule.MINUTES,
                    "minutes": 5,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{name}: {'criado' if created else 'já existia'} (a cada 5 min)."
                )
            )
