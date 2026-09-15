"""API pública do monólito (Django Ninja, in-process) — CONVENTION §1.

4 grupos por público, versionados sob `/api/v1/<grupo>/`, montados em `core/urls.py`. Cada
grupo é um `NinjaAPI` que chama o `interface/` dos módulos in-process (§3) — zero regra de
negócio aqui. Auth JWT compartilhada em `api/auth.py`.

⚠️ Os NOMES dos grupos são PLACEHOLDER (Victor não curtiu — «PENDÊNCIA», decidir depois). O
que vale é a LÓGICA (qual público cada um serve). Ver `plan/api-ninja-transicao.md`.
"""
