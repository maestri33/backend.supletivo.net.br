"""Customer service — find-or-create de pagadores no Asaas (porte do legado, ORM síncrono).

O Asaas /payments exige um customer. Mantemos o mapeamento local Customer(external_id UUID de borda)
<-> asaas_id. Diferença do legado (CONVENTION §4): casamos por **cpf_cnpj** (chave natural do pagador),
não pelo external_id-cola; `external_id` aqui é UUID de borda gerado por nós.
"""

import asyncio
import re
import uuid
from dataclasses import dataclass

from .client import AsaasError, get_client
from .models import Customer


class CustomerError(Exception):
    pass


@dataclass(frozen=True)
class PayerData:
    name: str
    cpf_cnpj: str
    email: str | None = None
    mobile_phone: str | None = None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _validate_cpf_cnpj(raw: str) -> str:
    digits = _digits(raw)
    if len(digits) not in (11, 14):
        raise CustomerError(
            f"invalid_cpf_cnpj: {len(digits)} dígitos (esperado 11 ou 14)"
        )
    return digits


async def _resolve_in_asaas(digits: str, payer: PayerData, external_ref: str) -> dict:
    """Recupera o customer no Asaas por cpfCnpj (evita órfão duplicado) ou cria."""
    async with get_client() as c:
        res = await c.list_customers({"cpfCnpj": digits, "limit": 1})
        data = res.get("data") or []
        if data:
            return data[0]
        return await c.create_customer(
            {
                "name": payer.name,
                "cpfCnpj": digits,
                "email": payer.email,
                "mobilePhone": payer.mobile_phone,
                "externalReference": external_ref,
                "notificationDisabled": True,
            }
        )


def find_or_create(payer: PayerData | None) -> Customer:
    """Casa por cpf_cnpj localmente; senão recupera/cria no Asaas e persiste."""
    if payer is None:
        raise CustomerError("payer_required")
    digits = _validate_cpf_cnpj(payer.cpf_cnpj)
    if not (payer.name or "").strip():
        raise CustomerError("payer_name_required")

    local = Customer.objects.filter(cpf_cnpj=digits).first()
    if local is not None:
        return local

    external_id = uuid.uuid4()
    try:
        data = asyncio.run(_resolve_in_asaas(digits, payer, str(external_id)))
    except AsaasError as e:
        raise CustomerError(f"asaas_customer_failed: {e.body}") from e

    return Customer.objects.create(
        external_id=external_id,
        asaas_id=data["id"],
        name=data.get("name") or payer.name,
        cpf_cnpj=_digits(data.get("cpfCnpj") or digits),
        email=data.get("email") or payer.email,
        mobile_phone=data.get("mobilePhone") or payer.mobile_phone,
    )
