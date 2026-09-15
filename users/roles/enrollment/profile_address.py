from __future__ import annotations

from users.address import interface as address_iface
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import _S, _require, _advance_to
from users.roles.enrollment.serializers import me_dict, _address_dict
from users.roles.enrollment import service

def get_address(*, user_external_id: str) -> dict:
    """GET do endereço + `missing_fields` (o que ainda falta preencher)."""
    _require(user_external_id)
    return _address_dict(user_external_id)


def set_address_cep(*, user_external_id: str, cep: str) -> dict:
    """POST do endereço (plan/13): body só `{cep}`. Acha no ViaCEP, grava e devolve o **EnrollmentMe
    canônico** (proposta #3) — o bloco `address.missing_fields` JÁ AVISA o que falta: rua achada →
    `["number"]`; cidade de CEP único → rua/bairro/número."""
    enr = _require(user_external_id, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    _advance_address(enr, user_external_id)
    return me_dict(enr)


def set_address_data(*, user_external_id: str, **fields) -> dict:
    """PATCH do endereço — preenche/CORRIGE: sobrescreve o que vier no payload (fix 2026-07-05,
    espelha o candidato: o `fill_empty` antigo descartava correções em silêncio). Valor vazio/None
    é ignorado. Devolve o EnrollmentMe canônico (proposta #3)."""
    enr = _require(user_external_id, _S.ADDRESS)
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    if fields:
        address_iface.patch(external_id=user_external_id, **fields)
    _advance_address(enr, user_external_id)
    return me_dict(enr)


def _advance_address(enr: Enrollment, user_external_id: str) -> None:
    """Endereço completo → EDUCATION. Comprovante validado em background (rejeição = ValidationBlock)."""
    if enr.status == _S.ADDRESS and address_iface.is_complete(
        address_iface.get_by_external_id(user_external_id)
    ):
        _advance_to(enr, _S.EDUCATION)

