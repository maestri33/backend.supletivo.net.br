"""
core/edge_cache.py — Utilitários de Edge Cache e Validação Condicional HTTP (Cloudflare-Ready).

Implementa:
- Decorator @edge_cache(...) para rotas Django Ninja e Django views padrão.
- Helper funcional apply_edge_cache(response, ...) para uso inline.
- EdgeCacheMiddleware para injeção de ETag determinístico e suporte a HTTP 304 (If-None-Match).
"""

from __future__ import annotations

import functools
import hashlib
import inspect
from typing import Any, Callable

from django.http import HttpRequest, HttpResponse, HttpResponseNotModified


DEFAULT_MAX_AGE = 60          # 1 minuto no navegador
DEFAULT_S_MAXAGE = 300        # 5 minutos no Cloudflare Edge
DEFAULT_STALE_WHILE_REVALIDATE = 600  # 10 minutos servindo cache antigo enquanto revalida
DEFAULT_VARY = ("Accept-Encoding", "Origin")


def apply_edge_cache(
    response: HttpResponse,
    *,
    max_age: int = DEFAULT_MAX_AGE,
    s_maxage: int = DEFAULT_S_MAXAGE,
    stale_while_revalidate: int = DEFAULT_STALE_WHILE_REVALIDATE,
    vary: tuple[str, ...] = DEFAULT_VARY,
) -> HttpResponse:
    """Aplica diretamente os cabeçalhos padronizados de cache em um HttpResponse."""
    response["Cache-Control"] = (
        f"public, max-age={max_age}, s-maxage={s_maxage}, "
        f"stale-while-revalidate={stale_while_revalidate}"
    )
    response["Vary"] = ", ".join(vary)
    return response


def edge_cache(
    *,
    max_age: int = DEFAULT_MAX_AGE,
    s_maxage: int = DEFAULT_S_MAXAGE,
    stale_while_revalidate: int = DEFAULT_STALE_WHILE_REVALIDATE,
    vary: tuple[str, ...] = DEFAULT_VARY,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator declarativo para endpoints Django Ninja ou Django CBV/FBV.

    Compatível com o sistema de assinaturas e injeção do Django Ninja:
    - Se a função já declarar `response: HttpResponse`, injeta os cabeçalhos nela.
    - Se a função NÃO declarar `response`, adiciona dinamicamente `response` ao __signature__
      para que o Django Ninja passe o `temporal_response` sem quebrar os outros parâmetros.
    """
    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(view_func)
        has_response_arg = "response" in sig.parameters

        if not has_response_arg:
            params = list(sig.parameters.values())
            resp_param = inspect.Parameter(
                "response",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=HttpResponse,
                default=None,
            )
            params.append(resp_param)
            new_sig = sig.replace(parameters=params)
        else:
            new_sig = sig

        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            resp = (
                kwargs.pop("response", None)
                if not has_response_arg
                else kwargs.get("response")
            )
            if resp is not None:
                apply_edge_cache(
                    resp,
                    max_age=max_age,
                    s_maxage=s_maxage,
                    stale_while_revalidate=stale_while_revalidate,
                    vary=vary,
                )
            return view_func(request, *args, **kwargs)

        wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator


class EdgeCacheMiddleware:
    """
    Middleware leve (Ponytail) para geração de ETag e suporte a HTTP 304 Not Modified.

    Executa após a renderização do corpo da resposta JSON:
    1. Calcula o ETag (SHA-256 truncado a 16 hexadecimais) para respostas 200 GET/HEAD com 'public'.
    2. Compara com 'If-None-Match' do cliente (navegador ou Cloudflare Anycast Cache).
    3. Se houver match, retorna HTTP 304 Not Modified sem payload (zero tráfego).
    4. Blindagem de segurança: Se a requisição possuir token JWT ou Cookies de sessão,
       força 'private, no-store' para impedir vazamento de dados em bordas compartilhadas.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        # Regra de Segurança: Nunca permita cache público de requisições autenticadas
        if request.headers.get("authorization") or request.COOKIES.get("sessionid"):
            if "public" in response.headers.get("Cache-Control", ""):
                response["Cache-Control"] = "private, no-store, must-revalidate"
                response.headers.pop("ETag", None)
            return response

        # Apenas requisições de leitura GET/HEAD bem-sucedidas
        if request.method in ("GET", "HEAD") and response.status_code == 200:
            cc = response.headers.get("Cache-Control", "")
            if "public" in cc and hasattr(response, "content") and response.content:
                # 1. Geração de ETag determinístico
                digest = hashlib.sha256(response.content).hexdigest()[:16]
                etag = f'"{digest}"'
                response["ETag"] = etag

                # 2. Garantir cabeçalho Vary
                existing_vary = response.headers.get("Vary", "")
                if not existing_vary:
                    response["Vary"] = "Accept-Encoding, Origin"
                elif "Origin" not in existing_vary:
                    needed_vary = {"Accept-Encoding", "Origin"}
                    current_vary = {v.strip() for v in existing_vary.split(",") if v.strip()}
                    response["Vary"] = ", ".join(sorted(current_vary | needed_vary))


                # 3. Avaliação de Revalidação Condicional (If-None-Match)
                inm = request.headers.get("if-none-match", "").strip()
                if inm and (inm == etag or inm == f"W/{etag}" or inm == "*"):
                    not_modified = HttpResponseNotModified()
                    # Transfere cabeçalhos canônicos da resposta original para o 304
                    for header in ("Cache-Control", "Vary", "ETag", "X-Platform-Version"):
                        if header in response.headers:
                            not_modified[header] = response.headers[header]
                    return not_modified

        return response
