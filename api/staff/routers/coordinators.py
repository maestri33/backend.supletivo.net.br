"""Router de Lideranças e Coordenadores de Polo (Staff)."""

from __future__ import annotations

from decimal import Decimal
from ninja import Router

from api.auth import require_superuser
from api.staff.schemas import CoordinatorOut
from hub.models import Hub
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.promoter.models import Promoter
from users.roles.student.models import Student
from finance.models import Commission

router = Router(tags=["staff"])


@router.get("/coordinators", response=list[CoordinatorOut], summary="Listagem completa de coordenadores e polos geridos")
def list_coordinators(request):
    """Retorna todas as lideranças que possuem papel de coordinator, com seus polos e métricas."""
    require_superuser(request.auth)
    base_users = roles.users_with_role("coordinator")
    pmap = profiles.get_map(base_users)

    # Carrega todos os hubs com coordenadores
    hubs = list(Hub.objects.select_related("coordinator", "address").all())
    promoters_all = list(Promoter.objects.select_related("hub", "user").all())
    students_all = list(Student.objects.select_related("hub").all())
    commissions_all = list(Commission.objects.filter(payee_role="coordinator").all())

    out = []
    for user in base_users:
        p = pmap.get(user.id)
        user_ext_id = str(user.external_id)

        # Polos coordenados por este usuário
        user_hubs = [h for h in hubs if h.coordinator_id == user.id]
        user_hub_ids = {h.id for h in user_hubs}

        # Promotores associados aos polos deste coordenador
        team_promoters = [pr for pr in promoters_all if pr.hub_id in user_hub_ids]

        # Alunos matriculados nos polos deste coordenador
        team_students = [
            st for st in students_all
            if st.hub_id in user_hub_ids
        ]

        # Comissões de coordenação deste usuário
        user_commissions = [c for c in commissions_all if c.payee_id == user.id]
        total_commissions = sum((c.amount for c in user_commissions), Decimal("0.00"))
        pending_commissions = sum(
            (c.amount for c in user_commissions if c.status in ("pending", "credited")),
            Decimal("0.00")
        )


        hubs_data = []
        for h in user_hubs:
            h_promoters_count = sum(1 for pr in promoters_all if pr.hub_id == h.id)
            h_students_count = sum(
                1 for st in students_all
                if st.hub_id == h.id
            )

            hubs_data.append({
                "external_id": str(h.external_id),
                "brand": h.brand,
                "is_default": h.is_default,
                "zipcode": h.address.zipcode if h.address else None,
                "city": h.address.city if h.address else None,
                "state": h.address.state if h.address else None,
                "street": h.address.street if h.address else None,
                "promoters_count": h_promoters_count,
                "students_count": h_students_count,
            })


        out.append({
            "external_id": user_ext_id,
            "name": p.name if p else None,
            "cpf": p.cpf if p else None,
            "phone": p.phone if p else None,
            "hubs": hubs_data,
            "hubs_count": len(user_hubs),
            "promoters_count": len(team_promoters),
            "students_count": len(team_students),
            "total_commission": f"{total_commissions:.2f}",
            "pending_commission": f"{pending_commissions:.2f}",
        })

    return out
