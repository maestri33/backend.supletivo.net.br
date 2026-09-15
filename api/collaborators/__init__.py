"""Grupo `collaborators` — funil do COLABORADOR: candidato → treino → promotor."""

from __future__ import annotations

from api.base import COMMON_ERROR_REGISTRY, build_group
from api.collaborators.routers.auth import router as auth_router
from api.collaborators.routers.candidate import router as candidate_router
from api.collaborators.routers.promoter import router as promoter_router
from api.collaborators.routers.training import router as training_router

_ERROR_REGISTRY = (
    COMMON_ERROR_REGISTRY
    + """
### Códigos específicos do colaborador (promotor)

| code | quando | extras |
|---|---|---|
| `WRONG_STATUS` | ação fora da etapa do wizard (409) | `expected_status` (etapa a abrir) |
| `NO_HUB` | nenhum polo disponível pro cadastro (422) | — |
| `INVALID_DOC_TYPE` | tipo de documento ≠ rg/cnh (422) | — |
| `PIX_INVALID` | chave Pix inválida ou não é do titular (422) | `reason` |
| `PROFILE_CPF_MISSING` | perfil sem CPF (refazer cadastro) (422) | — |
| `MATERIAL_NOT_FOUND` / `TRAINEE_NOT_FOUND` / `CANDIDATE_NOT_FOUND` / `PROMOTER_NOT_FOUND` | recurso não existe (404) | — |
| `MATERIAL_INACTIVE` | submissão em matéria desativada (422) | — |
| `ALREADY_GRADING` | já há uma resposta em correção (409) | — |
| `INVALID_AUDIO_TYPE` | áudio fora de mp3/m4a/aac/ogg/webm/wav (422) | — |
| `AUDIO_TOO_LARGE` | áudio acima de MAX_UPLOAD_MB (422) | — |
| `SELFIE_NOT_IN_REVIEW` | decisão de selfie fora de revisão (422) | `selfie_status` |
| `NOT_HUB_COORDINATOR` | coordenador não é do polo (403) | — |
| `CPF_EXISTS` / `PHONE_EXISTS` / `EMAIL_EXISTS` | cadastro duplicado (409) | — |
| `CPF_INVALID` / `PHONE_INVALID` / `CPF_NOT_FOUND` | dado rejeitado na validação (422) | — |
| `JOIN_PROFILE_INCOMPLETE` | conta de outro funil sem identidade completa (422) | `missing_fields` |
"""
)

api = build_group(
    "collaborators",
    "Funil do colaborador: candidato, treino, promotor.\n" + _ERROR_REGISTRY,
)

api.add_router("/auth", auth_router)
api.add_router("", candidate_router)
api.add_router("", training_router)
api.add_router("", promoter_router)

__all__ = ["api"]
