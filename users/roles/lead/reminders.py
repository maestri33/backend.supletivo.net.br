"""Leads elegíveis a LEMBRETE de pagamento — query do app dono do model (CONVENTION §3).

Quem decide *quando* lembrar e *como avisar* é o command `payment_reminder` (orquestra o notify). Aqui
mora só a REGRA DE ELEGIBILIDADE + o link já gerado, sem efeito colateral: não toca no gateway, não
muda status, não inventa URL. O lembrete reusa o link CURTO que já existe (`checkout_url_for`); lead
sem link ainda não é elegível (não há o que reenviar).

Janela conservadora (Victor 2026-06-30): só lembra quem está PENDING há pelo menos `min_age_hours`
(não importuna quem acabou de se cadastrar) e no máximo `max_age_hours` (não persegue lead morto). A
cadência (1 lembrete/dia) é garantida pela idempotência do notify no command — aqui é só leitura.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from users.profiles import interface as profiles
from users.roles.lead import service
from users.roles.lead.models import Lead


@dataclass(frozen=True)
class ReminderTarget:
    """Tudo que o command precisa pra notificar UM lead — sem ORM no command (§3)."""

    lead_external_id: str
    phone: str
    name: str
    gender: str | None
    payment_link: str
    age_hours: int


def due_reminders(
    *, min_age_hours: int = 24, max_age_hours: int = 168
) -> list[ReminderTarget]:
    """Leads PENDING dentro da janela [min, max] horas que TÊM telefone e link de pagamento.

    Leitura pura (nenhuma escrita). `self_study` (promotor estudando) fica de fora — é fluxo interno,
    não alvo de lembrete de venda. Ordena do mais antigo pro mais novo (prioriza quem está esperando há
    mais tempo). Lead sem profile/telefone ou sem link curto é pulado (não há canal nem o que reenviar).
    """
    now = timezone.now()
    oldest_allowed = now - timedelta(hours=max_age_hours)
    newest_allowed = now - timedelta(hours=min_age_hours)

    qs = (
        Lead.objects.filter(
            status=Lead.Status.PENDING,
            self_study=False,
            created_at__gte=oldest_allowed,
            created_at__lte=newest_allowed,
        )
        .select_related("user", "checkout")
        .order_by("created_at")
    )

    targets: list[ReminderTarget] = []
    for lead in qs:
        link = service.checkout_url_for(lead)
        if not link:
            continue  # sem link curto ainda: nada a reenviar
        profile = profiles.get(lead.user)
        phone = (profile.phone if profile else None) or None
        if not phone:
            continue  # sem telefone: sem canal
        first = ((profile.name or "").strip().split() or [""])[0] if profile else ""
        age_hours = int((now - lead.created_at).total_seconds() // 3600)
        targets.append(
            ReminderTarget(
                lead_external_id=str(lead.external_id),
                phone=phone,
                name=first,
                gender=(profile.gender if profile else None) or None,
                payment_link=link,
                age_hours=age_hours,
            )
        )
    return targets
