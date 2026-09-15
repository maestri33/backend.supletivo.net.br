from __future__ import annotations

from users.address import interface as address_iface
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    _S,
    _ADDRESS_FIELDS,
    _require,
    _set_status,
)
from users.roles.candidate.serializers import me_dict

def set_profile(
    *,
    user_external_id,
    mother_name=None,
    father_name=None,
    marital_status=None,
    birthplace=None,
    nationality=None,
) -> dict:
    cand = _require(user_external_id, _S.STARTED, _S.PROFILE)
    # identidade → SÓ no Profile (Victor 2026-06-16), nunca no candidate
    profiles.fill_identity(
        cand.user,
        mother_name=mother_name,
        father_name=father_name,
        marital_status=marital_status,
        birthplace=birthplace,
        nationality=nationality,
    )
    if cand.status == _S.STARTED:
        _set_status(cand, _S.PROFILE)
    return me_dict(cand)


def get_address(*, user_external_id) -> dict:
    """GET do endereço + `missing_fields` (o front renderiza input só do que falta)."""
    _require(user_external_id)
    data = address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )
    data["missing_fields"] = [f for f in _ADDRESS_FIELDS if not data.get(f)]
    return data


def set_address_cep(*, user_external_id, cep) -> dict:
    """Busca o CEP (ViaCEP) e preenche o endereço. Em cidade de CEP único a rua fica vazia p/ digitar."""
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    _advance_address(cand, user_external_id)
    return me_dict(cand)


def set_address_data(*, user_external_id, **fields) -> dict:
    """Preenche/CORRIGE os demais campos do endereço — sobrescreve o que vier no payload.

    Fix Marilu 2026-07-05: o `fill_empty` antigo só escrevia em campo VAZIO — corrigir um número
    errado era descartado em silêncio ("mandei, voltou"). Agora usa `patch` (sobrescreve); valor
    vazio/None no payload é ignorado (só muda o que o front mandou de verdade)."""
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    if fields:
        address_iface.patch(external_id=user_external_id, **fields)
    _advance_address(cand, user_external_id)
    return me_dict(cand)


def _advance_address(cand: Candidate, user_external_id) -> None:
    """Endereço completo → ADDRESS. Comprovante validado em background (rejeição = ValidationBlock)."""
    if cand.status == _S.PROFILE and address_iface.is_complete(
        address_iface.get_by_external_id(user_external_id)
    ):
        _set_status(cand, _S.ADDRESS)

