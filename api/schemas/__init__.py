"""Schemas compartilhados entre grupos da API Ninja (CONVENTION §12)."""

from __future__ import annotations

from api.schemas.address import AddressCepIn, AddressDataIn, PublicAddressOut
from api.schemas.auth import CheckIn, CheckOut, LoginIn, RefreshIn, TokenOut
from api.schemas.documents import ContractOut, DocClassifyOut
from api.schemas.student import StudentPlatformFields
from api.schemas.training import MaterialIn, MaterialUpdateIn

__all__ = [
    "AddressCepIn",
    "AddressDataIn",
    "PublicAddressOut",
    "CheckIn",
    "CheckOut",
    "LoginIn",
    "RefreshIn",
    "TokenOut",
    "StudentPlatformFields",
    "MaterialIn",
    "MaterialUpdateIn",
    "DocClassifyOut",
    "ContractOut",
]
