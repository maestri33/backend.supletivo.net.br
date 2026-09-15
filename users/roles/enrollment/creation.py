from __future__ import annotations

import structlog
from django.db import transaction

from users.exceptions import DomainError
from users.roles import interface as roles
from users.profiles import interface as profiles
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import _S, logger
from users.roles.enrollment import service

def create_from_lead(
    *, user, promoter, hub, self_study=False, bolsista=False
) -> Enrollment:
    """Cria o Enrollment(RG — documento primeiro, plan/13) ligado ao HUB herdado + promove a role
    `lead→enrollment`. Idempotente.

    Chamado DENTRO da transação do hook de pagamento (lead pago). Se o enrollment já existe (webhook
    re-tentou), devolve o existente sem duplicar nem re-promover. `bolsista` (F4): promotor
    pré-matriculado que bateu 3 leads pagos — auto-enroll SEM pagamento (não há Lead/Checkout).
    """
    existing = Enrollment.objects.filter(user=user).first()
    if existing is not None:
        return existing

    enrollment = Enrollment.objects.create(
        user=user,
        promoter=promoter,
        hub=hub,
        self_study=self_study,
        bolsista=bolsista,
        status=Enrollment.Status.RG,
    )
    if "enrollment" not in roles.active_roles(user):
        roles.promote(user, "enrollment")

    logger.info(
        "enrollment.created_from_lead",
        external_id=str(enrollment.external_id),
        hub=str(hub.external_id),
    )
    return enrollment

