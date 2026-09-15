"""Lógica do `address` (CONVENTION §3) — totalmente DMZ (spec address: só dentro da plataforma).

Resolve o endereço de um usuário pela borda (`external_id` → Profile → `profile.address`, §4);
o preenchimento por CEP reusa o tool `integrations/tools/cep` (ViaCEP), NÃO duplica lógica (§12).
Funções são a LÓGICA (não sabem de HTTP); a view traduz pra JSON/status.
"""

from __future__ import annotations

import re

import structlog
from asgiref.sync import async_to_sync
from django.conf import settings

from integrations.tools.cep.scripts import viacep
from users.address.models import Address
from users.exceptions import IntegrationError, NotFound, ValidationError
from users.profiles import interface as profiles

logger = structlog.get_logger()

# UFs válidas — valida o `state` num PATCH manual (o ViaCEP já devolve UF válida).
_UF = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}  # fmt: skip

# Campos que o PATCH "demais dados" pode editar (o CEP cuida de zipcode/street/.../state).
_PATCHABLE = (
    "zipcode",
    "street",
    "number",
    "complement",
    "neighborhood",
    "city",
    "state",
)


def _normalize_zipcode(value):
    if value in (None, ""):
        return value
    zipcode = re.sub(r"\D", "", str(value))
    if len(zipcode) != 8:
        raise ValidationError("CEP inválido.", code="CEP_INVALID")
    return zipcode


def create_empty() -> Address:
    """Cria um Address vazio. Chamado DENTRO da transação do provisionamento (auth §9)."""
    return Address.objects.create()


def get_by_external_id(external_id: str) -> Address | None:
    """Endereço do usuário (via `profile.address`). None se não tem profile/endereço."""
    return profiles.get_address(external_id)


def get_by_id(address_id: int) -> Address | None:
    return Address.objects.filter(pk=address_id).first()


def list_all(*, limit: int = 100, offset: int = 0) -> list[Address]:
    return list(Address.objects.order_by("-created_at")[offset : offset + limit])


def _viacep(cep: str) -> dict | None:
    """ViaCEP via tool de integração. None = CEP inexistente/inválido; fora do ar → IntegrationError."""
    if settings.TEST_EXTERNAL_ADAPTERS:
        from core.test_adapters import viacep_lookup

        return viacep_lookup(cep)
    try:
        return async_to_sync(viacep.lookup)(cep)
    except viacep.ViaCepUnavailable as exc:
        raise IntegrationError(
            "Serviço de consulta de CEP indisponível.", code="CEP_SERVICE_DOWN"
        ) from exc


def _require_address(external_id: str) -> Address:
    address = profiles.get_address(external_id)
    if address is None:
        raise NotFound(
            "Endereço não encontrado para este usuário.", code="ADDRESS_NOT_FOUND"
        )
    return address


def set_by_cep(*, external_id: str, cep: str) -> Address:
    """Valida o CEP, busca no ViaCEP e grava no endereço do usuário (spec address: já salva no db)."""
    address = _require_address(external_id)
    data = _viacep(cep)
    if data is None:
        raise ValidationError("CEP não encontrado ou inválido.", code="CEP_NOT_FOUND")

    address.zipcode = data["zipcode"]
    address.street = data["street"]
    address.neighborhood = data["neighborhood"]
    address.city = data["city"]
    address.state = data["state"]
    if data.get("complement"):
        address.complement = data["complement"]
    address.save()
    logger.info("address.cep_set", external_id=external_id, zipcode=data["zipcode"])
    return address


def fill_by_cep(address: Address, cep: str, *, number=None, complement=None) -> Address:
    """Preenche um Address (OBJETO) pelo CEP (ViaCEP) — uso genérico, ex.: o endereço do POLO, que não
    é de um user (não tem external_id). Reusa `_viacep`. Levanta `ValidationError` se o CEP não existir."""
    data = _viacep(cep)
    if data is None:
        raise ValidationError("CEP não encontrado ou inválido.", code="CEP_NOT_FOUND")
    address.zipcode = data["zipcode"]
    address.street = data["street"]
    address.neighborhood = data["neighborhood"]
    address.city = data["city"]
    address.state = data["state"]
    if data.get("complement"):
        address.complement = data["complement"]
    if number is not None:
        address.number = number
    if complement is not None:
        address.complement = complement
    address.save()
    logger.info("address.filled_by_cep", zipcode=data["zipcode"])
    return address


def patch(*, external_id: str, **fields) -> Address:
    """Atualiza os demais dados do endereço (number, complement, ...). Ignora chaves desconhecidas."""
    address = _require_address(external_id)

    state = fields.get("state")
    if state is not None and state.upper() not in _UF:
        raise ValidationError("UF inválida.", code="STATE_INVALID")

    changed = []
    for key in _PATCHABLE:
        if key in fields:
            value = fields[key]
            if key == "zipcode":
                value = _normalize_zipcode(value)
            setattr(address, key, value.upper() if key == "state" and value else value)
            changed.append(key)
    if changed:
        address.save()
    logger.info("address.patched", external_id=external_id, fields=changed)
    return address


def fill_empty(*, external_id: str, **fields) -> Address:
    """Preenche SÓ os campos que estão VAZIOS (Victor 2026-06-05): não sobrescreve o que o CEP já trouxe.

    Em cidade de CEP único o ViaCEP não traz a rua → o usuário a digita aqui (e o que o CEP preencheu
    fica intocado). Campos com valor não-vazio no payload mas já preenchidos no endereço são ignorados.
    """
    address = _require_address(external_id)

    state = fields.get("state")
    if state is not None and state and state.upper() not in _UF:
        raise ValidationError("UF inválida.", code="STATE_INVALID")

    changed = []
    for key in _PATCHABLE:
        incoming = fields.get(key)
        if key == "zipcode":
            incoming = _normalize_zipcode(incoming)
        current = getattr(address, key, None)
        # só preenche se veio valor E o campo está vazio hoje
        if incoming not in (None, "") and current in (None, ""):
            setattr(address, key, incoming.upper() if key == "state" else incoming)
            changed.append(key)
    if changed:
        address.save()
    logger.info("address.filled_empty", external_id=external_id, fields=changed)
    return address


# campos essenciais p/ o endereço ser considerado pronto (avançar o funil / anexar).
_REQUIRED = ("zipcode", "street", "number", "city", "state")


def is_complete(address: Address | None) -> bool:
    """True se os campos essenciais estão preenchidos (Victor: 'pra anexar, todos preenchidos')."""
    return bool(address) and all(getattr(address, f, None) for f in _REQUIRED)
