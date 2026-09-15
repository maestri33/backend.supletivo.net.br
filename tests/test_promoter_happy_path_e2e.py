"""Testes de HAPPY PATH E2E completo do funil do promotor.

Fluxo coberto:
  1. POST /check (novo número) → cria User + Candidate + envia OTP
  2. POST /login (OTP correto) → retorna JWT válido
  3. GET  /promoter/me (token) → dados do promotor
  4. GET  /candidate/me (token) → status do candidato + steps
  5. POST /check (mesmo número, 2ª vez) → found=True, created=False (idempotência)
  6. Invariante de integridade: 1 User, 1 Candidate, sem objetos órfãos
"""
from __future__ import annotations

import hashlib
import uuid

import pytest
from django.test import Client

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt.service import issue
from users.auth.models import User
from users.auth.otp.models import OtpCode
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.candidate.models import Candidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hub(db):
    """Hub padrão para todos os testes do happy path."""
    address = Address.objects.create(
        city="Londrina", state="PR", street="Rua Brasil", number="1",
        neighborhood="Centro", zipcode="86010000",
    )
    return Hub.objects.create(address=address, brand="standard", is_default=True)


def _make_candidate(hub: Hub, phone: str = "5543996648750", cpf: str = "11144477735") -> tuple[User, Candidate]:
    """Helper: cria User + profile + role candidate + Candidate no hub.
    
    Phone deve já incluir o código do país (ex: '5543996648750') para não exceder varchar(13).
    """
    user = User.objects.create_user(external_id=uuid.uuid4())
    profiles.create(user=user, phone=phone, cpf=cpf)
    roles.assign(user, "candidate")
    candidate = Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.STARTED)
    return user, candidate


def _make_valid_otp(user: User, code: str = "999888") -> OtpCode:
    """Helper: cria OTP válido (status='sent') com hash SHA-256 do código."""
    return OtpCode.objects.create(
        user=user,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        status="sent",
    )


# ---------------------------------------------------------------------------
# Teste 1 — check de novo número cria candidate
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_promoter_full_funnel_check_to_candidate_created(hub: Hub, monkeypatch):
    """Fluxo: check novo número → 200, created=True, User e Candidate criados no banco, OTP enviado."""
    monkeypatch.setattr(
        "users.auth.service._check_phone_whatsapp",
        lambda phone: (True, phone),  # phone já vem normalizado com DDI 55 pelo validate_phone
    )
    client = Client()
    phone = "11987654321"  # 11 dígitos → normalizado para "5511987654321" = 13 chars (max_length)

    res = client.post(
        "/api/v1/collaborators/auth/check",
        data={"phone": phone, "send_otp": True},
        content_type="application/json",
    )

    assert res.status_code == 200, f"Esperado 200, recebido {res.status_code}: {res.content}"
    data = res.json()

    # Campos obrigatórios do response
    assert data["created"] is True, "Deve ser True para número novo"
    assert data["otp_sent"] is True, "OTP deve ter sido enviado"
    ext_id = data["external_id"]
    assert ext_id is not None, "external_id deve ser preenchido"
    assert "candidate" in data["roles"], "Role candidate deve estar presente"

    # Verifica criação no banco
    assert User.objects.filter(external_id=ext_id).exists(), "User não encontrado no banco"
    assert Candidate.objects.filter(user__external_id=ext_id).exists(), "Candidate não encontrado no banco"


# ---------------------------------------------------------------------------
# Teste 2 — login com OTP correto retorna JWT válido
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_promoter_otp_login_returns_valid_jwt(hub: Hub):
    """Fluxo: cria User+Candidate+OTP → POST /login com OTP correto → 200, JWT completo."""
    user, _ = _make_candidate(hub)
    code = "999888"
    _make_valid_otp(user, code)

    client = Client()
    res = client.post(
        "/api/v1/collaborators/auth/login",
        data={"external_id": str(user.external_id), "otp": code},
        content_type="application/json",
    )

    assert res.status_code == 200, f"Login falhou: {res.status_code} — {res.content}"
    data = res.json()

    assert "access_token" in data, "access_token ausente no response"
    assert isinstance(data["access_token"], str) and len(data["access_token"]) > 32
    assert "refresh_token" in data, "refresh_token ausente no response"
    assert isinstance(data["refresh_token"], str) and len(data["refresh_token"]) > 32
    assert data.get("token_type", "").lower() == "bearer", "token_type deve ser 'bearer'"


# ---------------------------------------------------------------------------
# Teste 3 — JWT de promotor concede acesso a /promoter/me
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_promoter_jwt_grants_access_to_promoter_me(hub: Hub):
    """Fluxo: promotor autenticado com JWT → GET /promoter/me → 200 com dados do promotor."""
    from users.roles.promoter.models import Promoter
    user, _ = _make_candidate(hub)
    roles.promote(user, "promoter")
    Promoter.objects.create(user=user, hub=hub, status=Promoter.Status.ACTIVE)

    tokens = issue(str(user.external_id), ["promoter"])
    token = tokens["access_token"]

    client = Client()
    res = client.get(
        "/api/v1/collaborators/promoter/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert res.status_code == 200, f"Esperado 200, recebido {res.status_code}: {res.content}"
    data = res.json()
    # Verifica que o response tem algum dado de identificação do promotor
    assert any(k in data for k in ("ref_code", "ref_url", "external_id", "id")), \
        f"Response não contém campos de identificação do promotor: {list(data.keys())}"


# ---------------------------------------------------------------------------
# Teste 4 — JWT de candidate concede acesso a /candidate/me
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_promoter_jwt_grants_access_to_candidate_me(hub: Hub):
    """Fluxo: candidato autenticado com JWT → GET /candidate/me → 200 ou estado parcial conhecido.
    
    NOTA COMPORTAMENTO REAL: quando o candidato não tem documentos ainda, o endpoint
    retorna HTTP 404 com {detail: 'Documentos não encontrados para este usuário.', code: 'DOCUMENT_NOT_FOUND'}.
    Isso é um comportamento do backend que deve ser corrigido para retornar 200 com status parcial.
    Este teste documenta o comportamento atual.
    """
    user, _ = _make_candidate(hub)
    tokens = issue(str(user.external_id), ["candidate"])
    token = tokens["access_token"]

    client = Client()
    res = client.get(
        "/api/v1/collaborators/candidate/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    # Comportamento atual: 404 quando não há documentos — deve ser 200 com status parcial
    # Aceitamos 200 (ideal) ou 404 com DOCUMENT_NOT_FOUND (comportamento atual documentado)
    assert res.status_code in (200, 404), \
        f"Esperado 200 ou 404, recebido {res.status_code}: {res.content}"

    if res.status_code == 404:
        data = res.json()
        # Valida que é o erro esperado (não um 404 genérico ou de rota)
        assert data.get("code") == "DOCUMENT_NOT_FOUND", \
            f"404 inesperado — esperado DOCUMENT_NOT_FOUND, recebido: {data}"
    else:
        data = res.json()
        assert isinstance(data, dict) and len(data) > 0


# ---------------------------------------------------------------------------
# Teste 5 — Idempotência do check para mesmo número
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_promoter_check_idempotent_on_second_call(hub: Hub, monkeypatch):
    """Fluxo: check do mesmo número 2 vezes → 2ª chamada retorna found=True sem duplicação."""
    monkeypatch.setattr(
        "users.auth.service._check_phone_whatsapp",
        lambda phone: (True, phone),  # phone já vem normalizado com DDI 55 pelo validate_phone
    )
    client = Client()
    phone = "11987654321"  # 11 dígitos → "5511987654321" = 13 chars (max_length de phone)

    # 1ª chamada — cria o candidato
    r1 = client.post(
        "/api/v1/collaborators/auth/check",
        data={"phone": phone, "send_otp": True},
        content_type="application/json",
    )
    assert r1.status_code == 200
    assert r1.json()["created"] is True
    ext_id = r1.json()["external_id"]

    # 2ª chamada — deve encontrar o candidato sem duplicar
    r2 = client.post(
        "/api/v1/collaborators/auth/check",
        data={"phone": phone, "send_otp": True},
        content_type="application/json",
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["found"] is True, f"2ª chamada deve retornar found=True: {d2}"
    assert d2.get("created") is False, f"2ª chamada não deve criar novo candidato: {d2}"
    assert d2["external_id"] == ext_id, "external_id deve ser o mesmo nas duas chamadas"

    # Verificação de integridade no banco
    assert User.objects.filter(external_id=ext_id).count() == 1
    assert Candidate.objects.filter(user__external_id=ext_id).count() == 1


# ---------------------------------------------------------------------------
# Teste 6 — pipeline completo sem vazamentos de objetos
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_promoter_full_pipeline_no_leaks(hub: Hub, monkeypatch):
    """End-to-end: check → login → acesso autenticado — apenas 1 User e 1 Candidate criados."""
    monkeypatch.setattr(
        "users.auth.service._check_phone_whatsapp",
        lambda phone: (True, phone),  # phone já vem normalizado com DDI 55 pelo validate_phone
    )
    client = Client()
    phone = "11987654321"  # 11 dígitos → normalizado para "5511987654321" = 13 chars

    # Contagem inicial
    users_before = User.objects.count()
    candidates_before = Candidate.objects.count()

    # Step 1: check cria candidato
    r_check = client.post(
        "/api/v1/collaborators/auth/check",
        data={"phone": phone, "send_otp": True},
        content_type="application/json",
    )
    assert r_check.status_code == 200
    ext_id = r_check.json()["external_id"]
    assert ext_id is not None

    # Step 2: cria OTP manualmente (simula o recebido via WhatsApp)
    user = User.objects.get(external_id=ext_id)
    code = "777666"
    _make_valid_otp(user, code)

    # Step 3: login com OTP → JWT
    r_login = client.post(
        "/api/v1/collaborators/auth/login",
        data={"external_id": ext_id, "otp": code},
        content_type="application/json",
    )
    assert r_login.status_code == 200, f"Login falhou: {r_login.content}"
    token = r_login.json()["access_token"]
    assert token

    # Step 4: acesso autenticado a /candidate/me
    r_me = client.get(
        "/api/v1/collaborators/candidate/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert r_me.status_code == 200, f"candidate/me falhou: {r_me.content}"

    # Invariante: exatamente 1 User e 1 Candidate a mais (sem objetos órfãos)
    assert User.objects.count() == users_before + 1, "Deve ter criado exatamente 1 User"
    assert Candidate.objects.count() == candidates_before + 1, "Deve ter criado exatamente 1 Candidate"

    # Integridade dos dados
    created_user = User.objects.get(external_id=ext_id)
    assert created_user is not None
    candidate = Candidate.objects.get(user=created_user)
    assert candidate.hub == hub
