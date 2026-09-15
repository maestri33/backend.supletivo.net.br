"""Router da Árvore Genealógica de Captação e Downline (Staff)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from django.db.models import Count, Q
from ninja import Query, Router

from api.auth import require_superuser
from api.staff.schemas import NetworkTreeFilterSchema, NetworkTreeHubOut
from hub.models import Hub
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.lead.models import Lead
from users.roles.promoter.models import Promoter
from users.roles.student.models import Student

router = Router(tags=["staff"])


@router.get("/network/tree", response=list[NetworkTreeHubOut], summary="Árvore de captação e performance hierárquica (Downline)")
def get_network_tree(
    request,
    filters: NetworkTreeFilterSchema = Query(default=None),
):
    """Retorna o organograma de Coordenadores -> Polos -> Promotores -> Alunos com taxas de conversão."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, NetworkTreeFilterSchema) else NetworkTreeFilterSchema()
    hub = f.hub

    hubs_qs = Hub.objects.select_related("coordinator", "address").all()
    if hub:
        hubs_qs = hubs_qs.filter(external_id=hub)

    hubs = list(hubs_qs)
    if not hubs:
        return []

    # Batch load all promoters for all hubs in one query
    promoters = list(Promoter.objects.select_related("user").filter(hub__in=hubs))
    promoters_by_hub = defaultdict(list)
    for p in promoters:
        promoters_by_hub[p.hub_id].append(p)

    # Collect all users for bulk profile fetching
    coord_users = [h.coordinator for h in hubs if h.coordinator]
    prom_users = [p.user for p in promoters if p.user]
    all_users = coord_users + prom_users
    profile_map = profiles.get_map(all_users)

    # Bulk aggregate leads count & paid count per promoter user
    lead_stats_map = {}
    if prom_users:
        lead_stats = (
            Lead.objects.filter(promoter__in=prom_users)
            .values("promoter_id")
            .annotate(
                total_leads=Count("id"),
                paid_leads=Count("id", filter=Q(status=Lead.Status.PAID)),
            )
        )
        lead_stats_map = {
            row["promoter_id"]: (row["total_leads"], row["paid_leads"])
            for row in lead_stats
        }

    # Bulk aggregate students count per promoter user
    student_stats_map = {}
    if prom_users:
        student_stats = (
            Student.objects.filter(user__enrollment__promoter__in=prom_users)
            .values("user__enrollment__promoter_id")
            .annotate(total_students=Count("id"))
        )
        student_stats_map = {
            row["user__enrollment__promoter_id"]: row["total_students"]
            for row in student_stats
        }

    network_tree = []

    for h in hubs:
        coord_user = h.coordinator
        coord_prof = profile_map.get(coord_user.id) if coord_user else None

        hub_promoters = []
        total_hub_leads = 0
        total_hub_paid = 0

        for prom in promoters_by_hub.get(h.id, []):
            prom_user = prom.user
            prom_prof = profile_map.get(prom_user.id) if prom_user else None

            leads_count, paid_count = (
                lead_stats_map.get(prom_user.id, (0, 0)) if prom_user else (0, 0)
            )
            students_count = (
                student_stats_map.get(prom_user.id, 0) if prom_user else 0
            )

            conversion = (paid_count / leads_count * 100) if leads_count > 0 else 0.0

            total_hub_leads += leads_count
            total_hub_paid += paid_count

            hub_promoters.append({
                "external_id": str(prom.external_id),
                "user_external_id": str(prom_user.external_id) if prom_user else None,
                "name": prom_prof.name if prom_prof else "Promotor",
                "phone": prom_prof.phone if prom_prof else None,
                "status": prom.status,
                "leads_count": leads_count,
                "paid_count": paid_count,
                "students_count": students_count,
                "conversion_rate": round(conversion, 1),
            })

        hub_conversion = (total_hub_paid / total_hub_leads * 100) if total_hub_leads > 0 else 0.0

        network_tree.append({
            "hub_external_id": str(h.external_id),
            "brand": h.brand,
            "is_default": h.is_default,
            "coordinator": {
                "user_external_id": str(coord_user.external_id) if coord_user else None,
                "name": coord_prof.name if coord_prof else "Sem Coordenador",
                "phone": coord_prof.phone if coord_prof else None,
            },
            "metrics": {
                "total_promoters": len(hub_promoters),
                "total_leads": total_hub_leads,
                "total_paid": total_hub_paid,
                "conversion_rate": round(hub_conversion, 1),
            },
            "promoters": hub_promoters,
        })

    return network_tree
