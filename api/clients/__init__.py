"""Grupo `clients` — público do funil do ALUNO (**$$ ENTRA**):
lead → enrollment → student → veteran.
"""

from __future__ import annotations

from api.base import COMMON_ERROR_REGISTRY, build_group
from api.clients.routers.auth import router as auth_router
from api.clients.routers.blocks import router as blocks_router
from api.clients.routers.enrollment import router as enrollment_router
from api.clients.routers.lead import router as lead_router
from api.clients.routers.pricing import router as pricing_router
from api.clients.routers.student import _veteran_guard, router as student_router, veteran_me
from users.roles.enrollment import service as enrollment_iface
from users.roles.student import service as student_iface

_ERROR_REGISTRY = (
    COMMON_ERROR_REGISTRY
    + """
### Códigos específicos do aluno (clients)

| code | quando | extras |
|---|---|---|
| `WRONG_STATUS` | ação fora da etapa do wizard (409) | `expected_status` (etapa a abrir), `missing_fields` (se faltam campos do RG/perfil) |
| `SLOT_INVALID` | slot de foto desconhecido (422) | — |
| `CPF_EXISTS` / `PHONE_EXISTS` / `EMAIL_EXISTS` | cadastro duplicado (409) | — |
| `CPF_CONFLICT` | CPF já é de OUTRA conta no passo 3 do funil v2 (409) | — |
| `CPF_ALREADY_SET` | a conta já confirmou um CPF (409) | — |
| `EMAIL_CONFLICT` | e-mail já é de outra conta no passo 5 (409) | — |
| `EMAIL_INVALID` | e-mail malformado no passo 5 (422) | — |
| `PROFILE_INCOMPLETE` | checkout sem cpf/e-mail confirmados (409) | `missing_fields` |
| `ALREADY_PAID` | troca de pagamento após confirmação (409) | — |
| `CPF_INVALID` / `PHONE_INVALID` / `CPF_NOT_FOUND` | dado rejeitado na validação (422) | — |
| `CPF_SERVICE_DOWN` / `PHONE_SERVICE_DOWN` / `CEP_SERVICE_DOWN` | serviço externo fora (502) | — |
| `CEP_NOT_FOUND` / `STATE_INVALID` | endereço inválido (422) | — |
| `CHECKOUT_NOT_FOUND` / `STUDENT_NOT_FOUND` / `ENROLLMENT_NOT_FOUND` | recurso específico do aluno (404) | — |
| `BLOCK_NOT_FOUND` | bloco inválido/expirado (404) | — |
"""
)

api = build_group(
    "clients",
    "Funil do aluno: lead, enrollment, student, veteran.\n" + _ERROR_REGISTRY,
)

api.add_router("", pricing_router)
api.add_router("/auth", auth_router)
api.add_router("/lead", lead_router)
api.add_router("", enrollment_router)
api.add_router("", student_router)
api.add_router("", blocks_router)

__all__ = [
    "api",
    "veteran_me",
    "_veteran_guard",
    "student_iface",
    "enrollment_iface",
]
