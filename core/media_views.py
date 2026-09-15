"""View de /media/ com split público/privado + gate de DONO (Lane #4 — Victor 2026-07-08;
gate de dono 2026-07-10).

`core/urls.py` continua expondo `/media/<path>` (compat de URL: notify/Evolution buscam mídia
por essa rota), mas agora passa por um gate antes de servir o arquivo:

- prefixo PÚBLICO (fora de `settings.MEDIA_PRIVATE_PREFIXES` — ex.: `training/`, `ai/`) → serve
  direto, sem auth, reusando `django.views.static.serve` (mesma semântica de sempre: 404,
  If-Modified-Since, content-type por extensão).
- prefixo PRIVADO (`settings.MEDIA_PRIVATE_PREFIXES`: documents, selfie, diploma, receipt,
  student) → exige access token JWT válido (mesma validação do `api/auth.py:JWTAuth` — RS256,
  não-expirado, `type=access`, `token_version` batendo com o do User) E que o requisitante seja o
  DONO do arquivo, OU um REVISOR (coordenador/superuser). Sem token → 401; token válido mas sem
  direito → 403 (fail-closed).

GATE DE DONO (fecha o IDOR): os paths privados são `"<prefixo>/<token>.<ext>"` com token aleatório
(`core/media.py`, Victor 2026-06-21 — external_id NUNCA no path), então não há `token → dono`
direto. `core.media.owner_external_id_for_path` amarra o dono por MATCH EXATO do path nos campos
que guardam esses caminhos (RG/CNH/Certificate/AddressProof/Military → Document.user; Enrollment/
Candidate.selfie_image; StudentDiploma/StudentDocument → Student.user). Requisitante == dono → serve;
senão 403. Revisores (role `coordinator`, ou superuser) veem qualquer arquivo (revisão de docs).

LIMITAÇÕES CONHECIDAS (documentadas, fora do que dá pra fechar sem migration):
- `receipt/` (comprovante de payout a terceiro livre) NÃO tem dono-usuário no DB (`PaymentRequest.
  payee` é null no fluxo manual) → só REVISOR (superuser/coordenador) acessa; ninguém mais.
- Coordenador NÃO é escopado por hub aqui — qualquer coordenador vê mídia privada de qualquer hub
  (revisores são poucos e confiáveis; o IDOR crítico era usuário-de-funil vendo PII alheia, e esse
  fica fechado). Escopar por hub exigiria cruzar dono→hub e coordenador→hub.
- Arquivos privados órfãos (crop biométrico `documents/` de `enrollment/service.py`, que não é
  gravado em campo nenhum) não resolvem dono → só REVISOR acessa. Não são servidos a nenhum front.
- Selfies de auditoria (`audit/`, recorte de rosto do RG/selfie): `audit` ENTROU em
  `MEDIA_PRIVATE_PREFIXES` (2026-07-10). Como não têm dono resolvível (não são gravadas em campo de
  model — só existem no disco pra o time conferir), caem no caminho revisor-only: coordenador/
  superuser acessam, qualquer outro autenticado → 403. Nenhum front consome esses arquivos.

Fim de verdade (fora do escopo): índice `token → owner` no `save_media`, ou URL assinada por recurso.
"""

from __future__ import annotations

import posixpath

from django.conf import settings
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotFound,
    JsonResponse,
)
from django.views.static import serve as _static_serve

from core.media import is_private_media, owner_external_id_for_path
from users.auth.jwt import service as jwt_service

# Roles (claim do JWT) que revisam mídia de qualquer dono. Superuser (flag no DB) entra à parte.
_REVIEWER_ROLES = ("coordinator",)


def _bearer_token(request: HttpRequest) -> str | None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[len("bearer ") :].strip()
    return token or None


def _authenticated_principal(request: HttpRequest) -> tuple[str, list[str]] | None:
    """`(external_id, roles)` do access token válido, ou None. Mesma checagem do `api/auth.py:
    JWTAuth`: assinatura+exp+tipo (ninja-jwt) + token_version."""
    token = _bearer_token(request)
    if not token:
        return None
    try:
        payload = jwt_service.decode(token)
    except jwt_service.TokenError:
        return None
    external_id = payload.get("external_id", "")
    if not jwt_service.version_matches(external_id, payload.get("token_version")):
        return None
    return external_id, payload.get("roles", [])


def _is_superuser(external_id: str) -> bool:
    """Flag `is_superuser` no DB (staff nativo do Django) — não vem nos claims (ver api/auth.py)."""
    from django.contrib.auth import get_user_model

    return (
        get_user_model()
        .objects.filter(external_id=external_id, is_active=True, is_superuser=True)
        .exists()
    )


def _authorized_for_private(external_id: str, roles: list[str], path: str) -> bool:
    """Requisitante pode ver este arquivo privado? Dono OU revisor (coordenador/superuser)."""
    if any(r in _REVIEWER_ROLES for r in roles):  # revisor por claim: sem tocar o DB
        return True
    owner = owner_external_id_for_path(path)
    if owner is not None and owner == external_id:
        return True
    return _is_superuser(external_id)  # fallback só p/ não-dono não-coordenador (raro)


def media_serve(request: HttpRequest, path: str) -> HttpResponse:
    """Serve `MEDIA_ROOT/<path>`. Prefixo privado: sem JWT válido → 401; sem ser dono/revisor → 403.

    G1: normaliza o path ANTES de classificar/servir. Sem isso, `training/../documents/<tok>.jpg`
    era classificado pelo 1º segmento (`training`, público) e servido sem token — apesar de o
    arquivo final ser privado (`documents`). `normpath` resolve o `..`; se o resultado ainda escapa
    do root (`../` sobrando), 404 (não deixa `_static_serve` levantar SuspiciousFileOperation=500)."""
    norm = posixpath.normpath("/" + path).lstrip("/")
    if not norm or norm.startswith("../"):
        return HttpResponseNotFound()
    if is_private_media(norm):
        principal = _authenticated_principal(request)
        if principal is None:
            return JsonResponse({"detail": "Não autenticado."}, status=401)
        external_id, roles = principal
        if not _authorized_for_private(external_id, roles, norm):
            return JsonResponse({"detail": "Acesso negado."}, status=403)
    return _static_serve(request, norm, document_root=settings.MEDIA_ROOT)
