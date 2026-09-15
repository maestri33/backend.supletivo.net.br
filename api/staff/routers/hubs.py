"""Router de Gestão de Polos (Staff)."""

from __future__ import annotations

from ninja import Router

from api.auth import require_superuser
from api.staff.schemas import (
    HubAddressIn,
    HubAddressPatchIn,
    HubCreateIn,
    HubOut,
    PromoterOut,
    SetCoordinatorIn,
)
from hub import interface as hub_iface
from users.exceptions import NotFound, ValidationError
from users.profiles import interface as profiles
from users.roles import interface as roles

router = Router(tags=["staff"])

_HUB_ERROR_DETAIL = {
    "hub_not_found": "Polo não encontrado.",
    "coordinator_not_found": "Coordenador não encontrado.",
    "coordinator_not_promoter": "O coordenador precisa ser um promotor ativo.",
    "coordinator_required": "O polo deve obrigatoriamente ter um promotor selecionado como coordenador.",
    "address_not_found": "Endereço informado não encontrado.",
}


def _raise_hub_error(exc: Exception):
    slug = str(exc)
    if slug.startswith("invalid_brand:"):
        raise ValidationError(
            "Marca inválida (fora do catálogo).", code="INVALID_BRAND"
        ) from exc
    code = slug.upper()
    detail = _HUB_ERROR_DETAIL.get(slug, slug)
    if slug == "hub_not_found":
        raise NotFound(detail, code=code) from exc
    raise ValidationError(detail, code=code) from exc


def _hub_out(hub) -> dict:
    addr = hub.address
    coord = hub.coordinator
    coord_name = None
    if coord:
        p = profiles.get(coord)
        coord_name = p.name if p else None

    addr_data = None
    if addr:
        addr_data = {
            "cep": addr.zipcode,
            "zipcode": addr.zipcode,
            "street": addr.street,
            "number": addr.number,
            "complement": addr.complement,
            "neighborhood": addr.neighborhood,
            "city": addr.city,
            "state": addr.state,
        }

    return {
        "external_id": str(hub.external_id),
        "brand": hub.brand,
        "coordinator_external_id": (
            str(coord.external_id) if coord else None
        ),
        "coordinator_name": coord_name,
        "is_default": hub.is_default,
        "address": addr_data,
    }


@router.post("/hubs", response={201: HubOut}, summary="Criação de polo")
def create_hub(request, payload: HubCreateIn):
    """Cria um polo: marca do catálogo + coordenador promotor + endereço."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.create_hub(
            brand=payload.brand,
            coordinator_external_id=payload.coordinator_external_id,
            address_id=payload.address_id,
            cep=payload.cep,
            street=payload.street,
            number=payload.number,
            complement=payload.complement,
            neighborhood=payload.neighborhood,
            city=payload.city,
            state=payload.state,
            is_default=payload.is_default,
        )
    except hub_iface.HubError as exc:
        _raise_hub_error(exc)
    return 201, _hub_out(hub)


@router.get("/hubs", response=list[HubOut], summary="Listagem de polos")
def list_hubs(request):
    """Lista todos os polos cadastrados."""
    require_superuser(request.auth)
    return [_hub_out(h) for h in hub_iface.list_hubs()]


@router.get("/promoters", response=list[PromoterOut], summary="Listagem de promotores aptos a coordenar")
def list_promoters(request):
    """Lista promotores ativos para escolha de coordenador."""
    require_superuser(request.auth)
    base = roles.users_with_role("promoter")
    pmap = profiles.get_map(base)
    out = []
    for user in base:
        p = pmap.get(user.id)
        out.append(
            {
                "external_id": str(user.external_id),
                "name": p.name if p else None,
                "phone": p.phone if p else None,
                "cpf": p.cpf if p else None,
            }
        )
    return out



@router.put("/hubs/{external_id}/coordinator", response=HubOut, summary="Definir coordenador do polo")
def set_coordinator(request, external_id: str, payload: SetCoordinatorIn):
    """Designa ou troca o coordenador de um polo."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_coordinator(
            hub_external_id=external_id,
            coordinator_external_id=payload.coordinator_external_id,
        )
    except hub_iface.HubError as exc:
        _raise_hub_error(exc)
    return _hub_out(hub)


@router.put("/hubs/{external_id}/default", response=HubOut, summary="Marcar polo padrão")
def set_default_hub(request, external_id: str):
    """Marca polo como padrão para captação."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_default(external_id)
    except hub_iface.HubError as exc:
        _raise_hub_error(exc)
    return _hub_out(hub)


@router.patch("/hubs/{external_id}/address", response=HubOut, summary="Definir endereço do polo")
def set_hub_address(request, external_id: str, payload: HubAddressIn | HubAddressPatchIn):
    """Preenche endereço do polo por CEP."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_address(
            hub_external_id=external_id,
            cep=payload.cep or "",
            number=payload.number,
            complement=payload.complement,
        )
    except hub_iface.HubError as exc:
        _raise_hub_error(exc)
    return _hub_out(hub)
