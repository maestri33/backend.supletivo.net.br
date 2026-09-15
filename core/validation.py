"""Registro de validações/testes (pedido do Victor: rastrear no futuro).

Todo teste que a gente roda pode ser carimbado aqui (`record_check`) — fica salvo com flag + horário.
O `/status/` de cada integração mostra o último resultado por nome (`latest_checks`).
"""

from .models import ValidationCheck


def record_check(scope, name, passed, mode="", detail=""):
    """Grava um resultado de teste/validação (append-only). Retorna a linha criada."""
    return ValidationCheck.objects.create(
        scope=scope, name=name, passed=bool(passed), mode=mode, detail=detail
    )


def latest_checks(scope):
    """Último resultado por `name` dentro do `scope` — pro /status/ mostrar as flags."""
    out = {}
    for c in ValidationCheck.objects.filter(scope=scope).order_by("-checked_at"):
        if c.name not in out:
            out[c.name] = {
                "passed": c.passed,
                "mode": c.mode,
                "at": c.checked_at.isoformat(),
                "detail": c.detail,
            }
    return out
