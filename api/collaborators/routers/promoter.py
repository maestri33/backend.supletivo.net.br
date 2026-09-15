"""Router do Promotor ativo (Funil do Promotor)."""

from __future__ import annotations

from ninja import Router

from api.auth import require_roles
from api.collaborators.schemas import (
    PromoterCommissionOut,
    PromoterLeadInviteIn,
    PromoterLeadInviteOut,
    PromoterLeadOut,
    PromoterMeOut,
    PromoterPixIn,
    PromoterPixOut,
    PromoterPixTestOut,
    PromoterSummaryOut,
    StudyPricingOut,
    StudyStartIn,
    StudyStartOut,
)
from users.exceptions import NotFound
from users.roles.lead import service as lead_iface
from users.roles.promoter import service as promoter_iface

router = Router(tags=["promoter"])


def _guard(request, *allowed: str) -> str:
    """Gate de role por rota + devolve o external_id do USER logado."""
    require_roles(request.auth, *allowed)
    return request.auth.external_id


def _promoter(request):
    ext = _guard(request, "promoter")
    p = promoter_iface.get_by_user_external_id(ext)
    if p is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")
    return p


@router.get("/promoter/me", response=PromoterMeOut, summary="Painel do promotor")
def promoter_me(request):
    """Dados do painel, link ref e travas do promotor."""
    return promoter_iface.to_dict(_promoter(request))


@router.put("/promoter/pix", response=PromoterPixOut, summary="Cadastrar ou atualizar chave PIX do promotor")
def promoter_update_pix(request, payload: PromoterPixIn):
    """Atualiza a chave PIX do promotor com validação DICT no Asaas."""
    return promoter_iface.set_promoter_pix(
        promoter=_promoter(request),
        key=payload.pix_key,
        key_type=payload.key_type,
    )


@router.post("/promoter/pix/test", response=PromoterPixTestOut, summary="Testar chave PIX com micro-transferência de R$ 0,01")
def promoter_test_pix(request):
    """Dispara um PIX real de R$ 0,01 para a chave cadastrada para validação bancária."""
    return promoter_iface.test_promoter_pix(promoter=_promoter(request))


@router.get("/promoter/leads", response=list[PromoterLeadOut], summary="Leads do promotor (alias)")
@router.get("/promoter/me/leads", response=list[PromoterLeadOut], summary="Leads do promotor")
def promoter_leads(request):
    """Lista de leads captados pelo promotor."""
    return promoter_iface.list_leads(_promoter(request).user)


@router.post(
    "/promoter/leads/invite",
    response=PromoterLeadInviteOut,
    summary="Encaminhar convite para lead (alias)",
)
@router.post(
    "/promoter/me/leads/invite",
    response=PromoterLeadInviteOut,
    summary="Encaminhar convite para lead",
)
def promoter_lead_invite(request, payload: PromoterLeadInviteIn):
    """Valida telefone/CPF disponíveis e encaminha o link do promotor."""
    return promoter_iface.invite_lead(
        promoter=_promoter(request),
        phone=payload.phone,
        cpf=payload.cpf,
    )


@router.get(
    "/promoter/commissions",
    response=list[PromoterCommissionOut],
    summary="Comissões do promotor (alias)",
)
@router.get(
    "/promoter/me/commissions",
    response=list[PromoterCommissionOut],
    summary="Comissões do promotor",
)
def promoter_commissions(request):
    """Lista de comissões ganhas pelo promotor."""
    return promoter_iface.list_commissions(_promoter(request).user)


@router.get(
    "/promoter/summary", response=PromoterSummaryOut, summary="Resumo de metas e ganhos (alias)"
)
@router.get(
    "/promoter/me/summary", response=PromoterSummaryOut, summary="Resumo de metas e ganhos"
)
def promoter_summary(request):
    """Resumo da semana e métricas vitalícias."""
    return promoter_iface.summary(_promoter(request).user)


@router.get("/promoter/study/pricing", response=StudyPricingOut, summary="Preço de auto-matrícula de promotor")
def promoter_study_pricing(request):
    """Preço da auto-matrícula do promotor."""
    _guard(request, "promoter")
    return lead_iface.promoter_pricing()


@router.post("/promoter/study/start", response=StudyStartOut, summary="Iniciar auto-matrícula de promotor")
def promoter_study_start(request, payload: StudyStartIn):
    """Promotor estuda: cria matrícula especial com checkout."""
    promoter = _promoter(request)
    return lead_iface.create_self_study_lead(
        user=promoter.user, payment_method=payload.payment_method
    )
