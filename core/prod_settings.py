"""Overlay de produção — herda core.settings.

Hoje é PROPOSITALMENTE fino: DEBUG, ALLOWED_HOSTS, DATABASE_URL, CORS e os valores de
negócio vêm todos do `.env` (CONVENTION §6/§8), então `core.settings` já serve prod como
está. STATIC_ROOT também já vem do base (settings.py) — não se redefine aqui.

Este módulo existe como o ÚNICO ponto versionado e auditável de configuração prod-only
(substitui o antigo `prod_settings.py` que vivia hand-edited, fora do git, na raiz do
deploy — fragilidade de DR: sumia num clone novo / rebuild da LXC).

Topologia (2026-07-14): Cloudflare (TLS) → Caddy LXC 10.1.30.10 (manda
`X-Forwarded-Proto: https`) → nginx local 10.1.30.101:80 (agora repassa
`$http_x_forwarded_proto`) → Django :8000. Com o nginx repassando o proto certo,
o Django enxerga HTTPS e os cookies-Secure são seguros de emitir.

Estes cookies afetam SÓ o /admin do Django — a API pública é 100% JWT Bearer
(token no header, sem cookie de sessão), então o funil não depende disto. Mas
hardening correto é ter ligado (issue #23).
"""

from core.settings import *  # noqa: F401,F403

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(DEFAULT_CSRF_TRUSTED_ORIGINS + ["https://backend.supletivo.net.br"])
)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = False  # Caddy/Cloudflare já terminam o TLS
