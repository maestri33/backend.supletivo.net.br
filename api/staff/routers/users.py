"""Router de Gestão de Usuários, Matrículas e Resgates (Staff)."""

from __future__ import annotations

from ninja import Query, Router

from api.auth import require_superuser
from api.staff.schemas import (
    PhoneIn,
    PlatformCredentialsIn,
    StaffEnrollmentFilterSchema,
    StaffEnrollmentOut,
    StaffLeadFilterSchema,
    StaffLeadMarkPaidOut,
    StaffLeadOut,
    StaffPurgeFunnelUserOut,
    StaffStudentFilterSchema,
    StaffStudentOut,
    StaffStudentPlatformCredentialsOut,
    StaffUserFilterSchema,
    StaffUserOut,
    StaffUserPhoneOut,
)
from hub import interface as hub_iface
from users.auth import service as auth_iface
from users.exceptions import Conflict, NotFound
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment import service as enrollment_iface
from users.roles.lead import service as lead_iface
from users.roles.student import service as student_iface

router = Router(tags=["staff"])


@router.get("/leads", response=list[StaffLeadOut], tags=["lead"], summary="Listar todos os leads")
def list_all_leads(
    request,
    filters: StaffLeadFilterSchema = Query(default=None),
):
    """Lista todos os leads com filtro opcional por polo e status."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, StaffLeadFilterSchema) else StaffLeadFilterSchema()
    hub_obj = None
    if f.hub:
        hub_obj = hub_iface.get_by_external_id(f.hub)
        if hub_obj is None:
            raise NotFound("Polo não encontrado.", code="HUB_NOT_FOUND")
    leads = lead_iface.list_leads(hub=hub_obj, status=f.status)
    pmap = profiles.get_map([lead.user for lead in leads])
    return [lead_iface.lead_to_dict(lead, profile=pmap.get(lead.user_id)) for lead in leads]


@router.post("/leads/{external_id}/mark-paid", response=StaffLeadMarkPaidOut, summary="Marcar lead como pago manualmente")
def mark_lead_paid(request, external_id: str):
    """Força confirmação de pagamento de lead."""
    require_superuser(request.auth)
    lead = lead_iface.get_by_external_id(external_id)
    if lead is None:
        raise NotFound("Lead não encontrado.", code="LEAD_NOT_FOUND")
    if not lead.payment_id:
        raise Conflict("Lead não tem checkout de pagamento.", code="NO_CHECKOUT")
    lead_iface.mark_paid(
        provider=lead.payment.provider,
        provider_payment_id=lead.payment_id,
    )
    return {"detail": "Pagamento confirmado. Lead promovido a enrollment."}


@router.delete("/funnel-user", response=StaffPurgeFunnelUserOut, summary="Exclusão completa de usuário de teste")
def purge_funnel_user(
    request,
    user_external_id: str | None = None,
    lead_external_id: str | None = None,
    candidate_external_id: str | None = None,
    cpf: str | None = None,
    phone: str | None = None,
):
    """Apaga por completo usuário do funil (lead/candidato)."""
    require_superuser(request.auth)
    return roles.purge_funnel_user(
        user_external_id=user_external_id,
        lead_external_id=lead_external_id,
        candidate_external_id=candidate_external_id,
        cpf=cpf,
        phone=phone,
    )


@router.get("/enrollments", response=list[StaffEnrollmentOut], tags=["enrollment"], summary="Listar todas as matrículas")
def list_all_enrollments(
    request,
    filters: StaffEnrollmentFilterSchema = Query(default=None),
):
    """Matrículas de todos os polos."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, StaffEnrollmentFilterSchema) else StaffEnrollmentFilterSchema()
    return enrollment_iface.list_for_staff(hub_external_id=f.hub, status=f.status)


@router.get("/students", response=list[StaffStudentOut], tags=["student"], summary="Listar todos os alunos")
def list_all_students(
    request,
    filters: StaffStudentFilterSchema = Query(default=None),
):
    """Alunos de todos os polos."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, StaffStudentFilterSchema) else StaffStudentFilterSchema()
    return student_iface.list_for_staff(hub_external_id=f.hub, status=f.status)


@router.put("/students/{external_id}/platform-credentials", response=StaffStudentPlatformCredentialsOut, tags=["student"], summary="Atualizar credenciais da plataforma")
def set_student_platform_credentials(
    request, external_id: str, payload: PlatformCredentialsIn
):
    """Corrige login/senha da plataforma de um aluno já concluído."""
    require_superuser(request.auth)
    student = student_iface.set_platform_credentials(
        student_external_id=external_id,
        platform_login=payload.platform_login,
        platform_password=payload.platform_password,
        platform_url=payload.platform_url,
        platform_notes=payload.platform_notes,
    )
    return {"external_id": str(student.external_id), "status": student.status}


@router.get("/users", response=list[StaffUserOut], summary="Listagem geral de usuários")
def list_users(
    request,
    filters: StaffUserFilterSchema = Query(default=None),
    limit: int = 200,
):
    """Usuários e roles ativas da plataforma."""
    require_superuser(request.auth)
    from users.auth.models import User

    f = filters if isinstance(filters, StaffUserFilterSchema) else StaffUserFilterSchema()
    if f.role:
        base = roles.users_with_role(f.role)[:limit]
    else:
        base = list(User.objects.order_by("-id")[:limit])
    pmap = profiles.get_map(base)
    out = []
    for u in base:
        p = pmap.get(u.id)
        out.append(
            {
                "external_id": str(u.external_id),
                "name": p.name if p else None,
                "cpf": p.cpf if p else None,
                "phone": p.phone if p else None,
                "is_superuser": u.is_superuser,
                "roles": roles.active_roles(u),
            }
        )
    return out


@router.put("/users/{external_id}/phone", response=StaffUserPhoneOut, summary="Resgate de telefone de usuário")
def set_user_phone(request, external_id: str, payload: PhoneIn):
    """Troca de telefone de login em caso de perda de chip."""
    require_superuser(request.auth)
    return auth_iface.change_phone(
        user_external_id=external_id, new_phone=payload.phone
    )
