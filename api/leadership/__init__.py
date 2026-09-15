"""Grupo `leadership` — coordenador do polo (cargo de confiança)."""

from __future__ import annotations

from api.base import COMMON_ERROR_REGISTRY, build_group
from api.leadership.routers.auth import router as auth_router
from api.leadership.routers.candidates import router as candidates_router
from api.leadership.routers.enrollments import router as enrollments_router
from api.leadership.routers.leads import router as leads_router
from api.leadership.routers.promoters import router as promoters_router
from api.leadership.routers.reviews import router as reviews_router
from api.leadership.routers.students import router as students_router

_ERROR_REGISTRY = (
    COMMON_ERROR_REGISTRY
    + """
### Códigos específicos do coordenador (leadership)

| code | quando | extras |
|---|---|---|
| `WRONG_STATUS` | ação fora da etapa esperada | `expected_status` |
| `FEES_INCOMPLETE` | tentou concluir sem as 2 parcelas da taxa (409) | — |
| `FEE_ALREADY_PAID` / `FEE_ALREADY_SCHEDULED` | taxa repetida (409) | — |
| `FEE_QR_INVALID` / `FEE_QR_NO_DUE_DATE` | QR PIX inválido na taxa (422) | — |
| `RG_NOT_IN_REVIEW` / `DOC_NOT_IN_REVIEW` / `SELFIE_NOT_IN_REVIEW` | decide análise que não está em revisão (422) | `*_validation_status` |
| `ALREADY_APPROVED` | submeteu algo já decidido (409) | — |
| `EDUCATION_LEVEL_INVALID` / `EDUCATION_GRADE_OUT_OF_RANGE` | escolaridade fora da faixa (422) | `min`/`max` |
| `DOC_TYPE_LOCKED` / `DOC_TYPE_NOT_SET` | troca de tipo de doc travada (422) | — |
| `MILITARY_MALE_ONLY` | doc militar só p/ masculino (422) | — |
| `SLOT_INVALID` / `INVALID_KIND` / `INVALID_MATERIAL_KIND` | parâmetro inválido (422) | — |
| `MATERIAL_NOT_FOUND` / `MATERIAL_NOT_ASSIGNED` / `MATERIAL_INACTIVE` | material LMS (404/422) | — |
| `OPEN_PENDENCIES` / `PENDENCY_NOT_FOUND` | pendência do aluno (409/404) | — |
| `NO_PENDING_EXAM` / `DIPLOMA_NOT_ISSUED` | exame/diploma fora de ordem (409) | — |
| `NO_HUB` / `COMMISSION_PAYEE_INVALID` / `PIX_INVALID` | comissão/pix (422) | — |
| `NOT_HUB_COORDINATOR` | loga como coordenador mas não coordena nenhum polo (403) | — |

### Paginação
`GET /students` usa `limit`/`offset` e devolve `{items, total, limit, offset}` (`PaginatedOut`).
Demais listas são arrays diretos.
"""
)

api = build_group(
    "leadership",
    "Coordenador do polo (hub): aprovações, acesso, taxas, diploma." + _ERROR_REGISTRY,
)

api.add_router("/auth", auth_router)
api.add_router("", leads_router)
api.add_router("", enrollments_router)
api.add_router("", reviews_router)
api.add_router("", students_router)
api.add_router("", candidates_router)
api.add_router("", promoters_router)

__all__ = ["api"]
