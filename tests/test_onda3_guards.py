"""Guardas de health e limpeza de CoT."""


# ───────────────────────── G18: CoT truncado não vaza ─────────────────────────
def test_g18_think_fechado_removido():
    from integrations.ai.service import _strip_think

    assert _strip_think("<think>raciocínio</think>Olá!") == "Olá!"


def test_g18_think_truncado_sem_fechamento_removido():
    """<think> aberto sem </think> (resposta cortada por max_tokens) — o raciocínio cru não pode
    chegar ao WhatsApp. Antes vazava (o regex não casava o par)."""
    from integrations.ai.service import _strip_think

    truncado = "Resposta parcial <think>agora vou pensar: o cliente pediu"
    out = _strip_think(truncado)
    assert "pensar" not in out
    assert out == "Resposta parcial"


# ───────────────────────── G20: gate de staff-health ─────────────────────────
def test_g20_health_usa_require_superuser():
    """O gate estava `require_roles(..., 'staff')`, que sempre 403 (staff não é role, é
    is_superuser) — barrava até o superuser. Deve usar require_superuser."""
    import inspect

    from api.health import router as health

    src = inspect.getsource(health)
    assert "require_superuser(request.auth)" in src
    assert 'require_roles(request.auth, "staff")' not in src
