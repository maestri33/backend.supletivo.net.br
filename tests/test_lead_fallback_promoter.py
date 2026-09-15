"""Testes da cascata de fallback do _resolve_promoter (Issue #35).

Garante que um lead NUNCA é perdido por falta de coordenador/hub padrão — o endpoint
POST /api/v1/clients/auth/check não pode retornar 422 `no_default_promoter` se existir
qualquer hub com coordenador ativo OU qualquer superuser no sistema.
"""

import uuid

import pytest

from hub.models import Hub
from users.auth.models import User
from users.roles.lead.service import LeadError, _resolve_promoter


@pytest.fixture
def _clean_hubs(db):
    """Remove todos os hubs para testar cenários de fallback."""
    Hub.objects.all().delete()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        is_superuser=True,
        is_active=True,
    )


@pytest.fixture
def coordinator_user(db):
    return User.objects.create_user(
        is_active=True,
    )


@pytest.fixture
def default_hub(db, coordinator_user):
    from users.address import interface as address_iface

    address = address_iface.create_empty()
    return Hub.objects.create(
        brand="V7M",
        coordinator=coordinator_user,
        is_default=True,
        address=address,
    )


@pytest.fixture
def non_default_hub(db, coordinator_user):
    from users.address import interface as address_iface

    address = address_iface.create_empty()
    return Hub.objects.create(
        brand="V7M",
        coordinator=coordinator_user,
        is_default=False,
        address=address,
    )


# ── Cenário 1: Hub padrão com coordenador ativo ─────────────────────────────


@pytest.mark.django_db
def test_resolve_promoter_default_hub(default_hub, coordinator_user):
    """Sem ref → coordenador do hub padrão (caminho normal)."""
    result = _resolve_promoter(None)
    assert result == coordinator_user


# ── Cenário 2: Sem hub padrão, mas com hub qualquer ─────────────────────────


@pytest.mark.django_db
def test_resolve_promoter_fallback_any_hub(_clean_hubs, non_default_hub, coordinator_user):
    """Sem hub padrão → cai no coordenador de qualquer hub ativo."""
    result = _resolve_promoter(None)
    assert result == coordinator_user


# ── Cenário 3: Sem hubs → fallback pro staff ─────────────────────────────────


@pytest.mark.django_db
def test_resolve_promoter_fallback_staff(_clean_hubs, staff_user):
    """Sem hub nenhum → cai no primeiro superuser ativo (último recurso)."""
    result = _resolve_promoter(None)
    assert result == staff_user


# ── Cenário 4: Absolutamente ninguém → LeadError ────────────────────────────


@pytest.mark.django_db
def test_resolve_promoter_no_one_raises(_clean_hubs):
    """Sem hubs, sem staff, sem nada → LeadError (seed_defaults não rodou)."""
    # Garante que NÃO há superusers ativos
    User.objects.filter(is_superuser=True).update(is_active=False)
    with pytest.raises(LeadError, match="no_default_promoter"):
        _resolve_promoter(None)


# ── Cenário 5: Ref inválido → fallback funciona ─────────────────────────────


@pytest.mark.django_db
def test_resolve_promoter_bad_ref_falls_through(default_hub, coordinator_user):
    """Ref inválido (UUID que não existe) → cai no hub padrão, sem 422."""
    result = _resolve_promoter(str(uuid.uuid4()))
    assert result == coordinator_user


# ── Cenário 6: Hub padrão com coordenador INATIVO → cai no fallback 2 ───────


@pytest.mark.django_db
def test_resolve_promoter_inactive_coordinator_fallback(db, staff_user):
    """Coordenador do hub padrão está inativo → cai no staff (fallback 3)."""
    from users.address import interface as address_iface

    inactive_coord = User.objects.create_user(
        is_active=False,
    )
    address = address_iface.create_empty()
    Hub.objects.create(
        brand="V7M",
        coordinator=inactive_coord,
        is_default=True,
        address=address,
    )
    # Sem coordenador ativo em nenhum hub → cai no staff
    result = _resolve_promoter(None)
    assert result == staff_user
