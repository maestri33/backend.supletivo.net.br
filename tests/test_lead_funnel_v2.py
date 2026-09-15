"""Funil do lead v2 (protótipo 2026-07-18) — a API se molda ao protótipo (DOCUMENTACAO).

Caminho canônico SEM register: [1] telefone (o `check` CRIA a conta + Lead + OTP) → [2] OTP →
[3] CPF (`/lead/identity`, identidade pro pergaminho) → [5] e-mail (`/lead/email`) →
[6] checkout (`/lead/checkout`, criável e TROCÁVEL). Contratos de segurança testados:
`CPF_CONFLICT` (notifica o titular + purga a conta da tentativa), `EMAIL_CONFLICT`,
`PROFILE_INCOMPLETE` e `ALREADY_PAID`.

In-process via Django test Client (stack HTTP real: URLs, middleware, handlers, JWT do Ninja).
TEST_MODE: identidade sintética do CPFHub, WhatsApp sempre "existe", OTP fixo (000000).
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.django_db

BASE = "/api/v1/clients"
OTP = "000000"  # TEST_MODE_OTP_CODE (users/auth/otp/service.py)


def _valid_cpf(seed9: str) -> str:
    """Gera um CPF VÁLIDO a partir dos 9 primeiros dígitos (mesmo DV do users/auth/validation)."""
    assert len(seed9) == 9 and seed9.isdigit()

    def dv(digits: str) -> str:
        weights = range(len(digits) + 1, 1, -1)
        total = sum(int(d) * w for d, w in zip(digits, weights))
        rest = (total * 10) % 11
        return "0" if rest == 10 else str(rest)

    d1 = dv(seed9)
    return seed9 + d1 + dv(seed9 + d1)


def _json(client, method, path, body, token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return getattr(client, method)(
        f"{BASE}{path}",
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )


def _enter(client, phone: str, ref: str | None = None) -> str:
    """Passos 1-2 do funil: check (cria a conta) + login por OTP. Devolve o access token."""
    body: dict = {"phone": phone}
    if ref:
        body["ref"] = ref
    r = _json(client, "post", "/auth/check", body)
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["created"] is True, data
    r = _json(
        client, "post", "/auth/login", {"external_id": data["external_id"], "otp": OTP}
    )
    assert r.status_code == 200, r.content
    return r.json()["access_token"]


@pytest.fixture
def default_hub():
    """Hub padrão + coordenador (fallback de captação: lead sem `ref` cai neste polo)."""
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User

    coord = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(city="São Paulo", state="SP")
    Hub.objects.create(address=addr, brand="e2e", coordinator=coord, is_default=True)
    return coord


# ── [1] telefone: o check CRIA a conta (captura) ─────────────────────────────


def test_check_cria_conta_lead_com_otp(client, default_hub):
    """Número novo + WhatsApp ok → conta nasce no check: User+Profile(phone, SEM cpf)+role lead+
    Lead (promotor padrão) + OTP no mesmo passo. `found` continua honesto (false) + `created`."""
    from users.auth.models import User
    from users.roles import interface as roles
    from users.roles.lead.models import Lead

    r = _json(client, "post", "/auth/check", {"phone": "11987650001"})
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["found"] is False
    assert data["created"] is True
    assert data["external_id"]
    assert data["otp_sent"] is True
    assert data["roles"] == ["lead"]

    user = User.objects.get(external_id=data["external_id"])
    assert roles.active_roles(user) == ["lead"]
    assert user.profile.cpf is None  # CPF entra no passo 3
    assert user.profile.phone == "5511987650001"
    lead = Lead.objects.get(user=user)
    assert lead.promoter == default_hub  # sem ref → promotor padrão
    assert getattr(lead, "checkout", None) is None  # checkout SÓ no passo 6


def test_check_de_conta_existente_nao_recria(client, default_hub):
    """Segundo check do MESMO número → found:true (login normal), sem criar de novo."""
    from users.auth.models import User

    _json(client, "post", "/auth/check", {"phone": "11987650002"})
    total = User.objects.count()
    r = _json(client, "post", "/auth/check", {"phone": "11987650002"})
    data = r.json()
    assert data["found"] is True
    assert data["created"] is False
    assert User.objects.count() == total


def test_check_sem_whatsapp_nao_cria(client, default_hub, monkeypatch):
    """WhatsApp indisponível (serviço fora) → NÃO cria conta; `whatsapp:null` (front avisa)."""
    from users.auth import service as auth_service
    from users.auth.models import User
    from users.exceptions import IntegrationError

    def _down(phone):
        raise IntegrationError("fora", code="PHONE_SERVICE_DOWN")

    monkeypatch.setattr(auth_service, "_check_phone_whatsapp", _down)
    total = User.objects.count()
    r = _json(client, "post", "/auth/check", {"phone": "11987650003"})
    assert r.status_code == 200
    data = r.json()
    assert data["created"] is False
    assert data["found"] is False
    assert data["whatsapp"] is None
    assert User.objects.count() == total


# ── [1] telefone: o selo "Indicado por …" do `?ref=` (público) ───────────────


@pytest.fixture
def promoter(default_hub):
    """Promotor ATIVO com nome no profile — a fonte do selo "Indicado por …" da tela 1."""
    from hub.models import Hub
    from users.auth.models import User
    from users.profiles import interface as profiles
    from users.roles.promoter.models import Promoter

    user = User.objects.create_user(external_id=uuid.uuid4())
    profiles.create(
        user=user, cpf=None, phone="5511987659999", name="Joana Ribeiro dos Santos"
    )
    Promoter.objects.create(user=user, hub=Hub.objects.get(is_default=True))
    return user


def test_referral_devolve_so_o_primeiro_nome(client, promoter):
    """`?ref=` de promotor ativo → SÓ o primeiro nome: a rota é pública, não pode virar
    consulta de cadastro (o ref circula em link compartilhável)."""
    r = client.get(f"{BASE}/referral/{promoter.external_id}")
    assert r.status_code == 200, r.content
    assert r.json() == {"name": "Joana"}


def test_referral_que_nao_vale_devolve_null_sem_erro(client, promoter):
    """Ref malformado / inexistente / de promotor SUSPENSO → 200 `name:null`, nunca 404: o link
    velho continua abrindo o funil (atribuído ao promotor padrão), só não desenha o selo."""
    from users.roles.promoter.models import Promoter

    assert client.get(f"{BASE}/referral/nao-e-uuid").json() == {"name": None}
    assert client.get(f"{BASE}/referral/{uuid.uuid4()}").json() == {"name": None}

    Promoter.objects.filter(user=promoter).update(status=Promoter.Status.SUSPENDED)
    assert client.get(f"{BASE}/referral/{promoter.external_id}").json() == {
        "name": None
    }


def test_referral_de_promotor_sem_nome_devolve_null(client, default_hub):
    """Promotor ativo mas com o profile ainda sem `name` (nasce vazio) → null, não string vazia."""
    from hub.models import Hub
    from users.auth.models import User
    from users.profiles import interface as profiles
    from users.roles.promoter.models import Promoter

    user = User.objects.create_user(external_id=uuid.uuid4())
    profiles.create(user=user, cpf=None, phone="5511987659998")
    Promoter.objects.create(user=user, hub=Hub.objects.get(is_default=True))

    assert client.get(f"{BASE}/referral/{user.external_id}").json() == {"name": None}


# ── [1] telefone: foto do WhatsApp (pergaminho da tela 3-4) ──────────────────


def test_captura_agenda_busca_da_foto_do_whatsapp(client, default_hub, monkeypatch):
    """Conta nascendo no check → agenda `fetch_whatsapp_avatar` (Django-Q, best-effort).
    A foto NÃO é buscada dentro do request — o check não pode pagar essa latência."""
    import django_q.tasks

    from users.profiles.models import Profile

    enqueued: list[tuple] = []
    monkeypatch.setattr(
        django_q.tasks, "async_task", lambda *a, **kw: enqueued.append(a)
    )

    r = _json(client, "post", "/auth/check", {"phone": "11987650020"})
    assert r.json()["created"] is True
    profile = Profile.objects.get(phone="5511987650020")
    assert ("users.roles.lead.tasks.fetch_whatsapp_avatar", profile.pk) in [
        (a[0], a[1]) for a in enqueued
    ]


def test_task_da_foto_grava_no_profile(client, default_hub, monkeypatch, settings):
    """Task busca a URL (modo remote → notify-server) e grava; 2ª rodada é no-op
    (não sobrescreve — a foto que o lead viu no pergaminho não muda embaixo dele)."""
    from users.profiles.models import Profile
    from users.roles.lead import tasks

    _json(client, "post", "/auth/check", {"phone": "11987650021"})
    profile = Profile.objects.get(phone="5511987650021")

    settings.TEST_MODE = False
    url = "https://pps.whatsapp.net/v/t61/abc123.jpg"
    monkeypatch.setattr("notify.sdk.client.phone_avatar", lambda number: url)

    assert tasks.fetch_whatsapp_avatar(profile.pk) == "ok"
    profile.refresh_from_db()
    assert profile.whatsapp_photo_url == url

    monkeypatch.setattr("notify.sdk.client.phone_avatar", lambda number: "OUTRA")
    assert tasks.fetch_whatsapp_avatar(profile.pk) == "already_set"
    profile.refresh_from_db()
    assert profile.whatsapp_photo_url == url


def test_task_sem_foto_ou_com_erro_nao_quebra(
    client, default_hub, monkeypatch, settings
):
    """Sem foto no zap → `no_photo` e o profile fica nulo (front usa monograma).
    Serviço fora → `failed`, best-effort SEM retry: foto é enfeite, não dado."""
    from users.profiles.models import Profile
    from users.roles.lead import tasks

    _json(client, "post", "/auth/check", {"phone": "11987650022"})
    profile = Profile.objects.get(phone="5511987650022")

    settings.TEST_MODE = False
    monkeypatch.setattr("notify.sdk.client.phone_avatar", lambda number: None)
    assert tasks.fetch_whatsapp_avatar(profile.pk) == "no_photo"
    profile.refresh_from_db()
    assert profile.whatsapp_photo_url is None

    def _boom(number):
        raise RuntimeError("evolution fora")

    monkeypatch.setattr("notify.sdk.client.phone_avatar", _boom)
    assert tasks.fetch_whatsapp_avatar(profile.pk) == "failed"


def test_identity_devolve_a_foto_capturada(client, default_hub):
    """Pergaminho com retrato: a foto capturada na criação da conta sai no /lead/identity."""
    from users.profiles.models import Profile

    token = _enter(client, "11987650023")
    url = "https://pps.whatsapp.net/v/t61/retrato.jpg"
    Profile.objects.filter(phone="5511987650023").update(whatsapp_photo_url=url)

    r = _json(client, "post", "/lead/identity", {"cpf": _valid_cpf("398765432")}, token)
    assert r.status_code == 200, r.content
    assert r.json()["photo"] == url


# ── [2] OTP: incorreto × expirado são desfechos DIFERENTES ───────────────────
# O front escolhe telas diferentes por eles (👀 "digita de novo" × ⏳ "já mandei outro"), então
# o 401 precisa dizer QUAL dos dois foi. Antes os dois vinham como OTP_INVALID e a pessoa que
# queimou as tentativas ficava vendo "código incorreto" pra sempre — inclusive com o código certo.


def _nascer(client, phone: str) -> str:
    """Passo 1 só: cria a conta e devolve o external_id (sem consumir o OTP)."""
    r = _json(client, "post", "/auth/check", {"phone": phone})
    assert r.status_code == 200, r.content
    return r.json()["external_id"]


def test_otp_errado_e_invalid_e_o_codigo_continua_valendo(client, default_hub):
    """Errou o código: 401 OTP_INVALID — e o código certo AINDA entra logo depois."""
    external_id = _nascer(client, "11987650030")

    r = _json(
        client, "post", "/auth/login", {"external_id": external_id, "otp": "999999"}
    )
    assert r.status_code == 401, r.content
    assert r.json()["code"] == "OTP_INVALID"

    r = _json(client, "post", "/auth/login", {"external_id": external_id, "otp": OTP})
    assert r.status_code == 200, r.content
    assert r.json()["access_token"]


def test_otp_vencido_e_expired(client, default_hub, settings):
    """Passou do TTL: 401 OTP_EXPIRED — o front abre o ⏳ e dispara um código novo."""
    external_id = _nascer(client, "11987650031")
    settings.OTP_TTL_S = 0  # tudo que já existe nasceu "velho demais"

    r = _json(client, "post", "/auth/login", {"external_id": external_id, "otp": OTP})
    assert r.status_code == 401, r.content
    assert r.json()["code"] == "OTP_EXPIRED"


def test_otp_com_tentativas_esgotadas_vira_expired(client, default_hub, settings):
    """Queimou as tentativas: o código MORREU → OTP_EXPIRED, mesmo digitando o certo.

    É o beco sem saída que motivou a mudança: sem esta distinção o app repetia "código
    incorreto" indefinidamente e ninguém descobria que o caminho era pedir outro.
    """
    settings.OTP_MAX_ATTEMPTS = 2
    external_id = _nascer(client, "11987650032")

    for _ in range(2):
        r = _json(
            client, "post", "/auth/login", {"external_id": external_id, "otp": "999999"}
        )
        assert r.status_code == 401, r.content

    r = _json(client, "post", "/auth/login", {"external_id": external_id, "otp": OTP})
    assert r.status_code == 401, r.content
    assert r.json()["code"] == "OTP_EXPIRED"


def test_otp_ja_usado_nao_entra_de_novo(client, default_hub):
    """OTP é de uso único: repetir o mesmo código não vira uma segunda sessão."""
    external_id = _nascer(client, "11987650033")

    r = _json(client, "post", "/auth/login", {"external_id": external_id, "otp": OTP})
    assert r.status_code == 200, r.content

    r = _json(client, "post", "/auth/login", {"external_id": external_id, "otp": OTP})
    assert r.status_code == 401, r.content
    assert r.json()["code"] == "OTP_EXPIRED"


def test_login_de_external_id_desconhecido_e_404(client, default_hub):
    """Sessão velha apontando pra um usuário que não existe: 404 → o front recomeça o funil."""
    r = _json(
        client, "post", "/auth/login", {"external_id": str(uuid.uuid4()), "otp": OTP}
    )
    assert r.status_code == 404, r.content
    assert r.json()["code"] == "USER_NOT_FOUND"


def test_reenvio_pelo_check_respeita_o_rate_limit(client, default_hub):
    """Reenvio é `POST /auth/check` de novo: rate-limitado devolve `otp_wait` (não é erro).

    `otp_sent:false` + `otp_wait` = um código recente JÁ saiu — a tela do OTP segue sendo o
    lugar certo, só com o cooldown restante no botão.
    """
    phone = "11987650034"
    _nascer(client, phone)

    r = _json(client, "post", "/auth/check", {"phone": phone})
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["found"] is True
    assert data["otp_sent"] is False
    assert data["otp_wait"] and data["otp_wait"] > 0


# ── [3] CPF: identidade (pergaminho) + contrato de segurança ─────────────────


def test_identity_confirma_cpf_e_devolve_pergaminho(client, default_hub):
    """CPF válido e novo → grava no profile e devolve nome/nascimento/sexo (pergaminho)."""
    from users.profiles.models import Profile

    token = _enter(client, "11987650010")
    cpf = _valid_cpf("529982247")
    r = _json(client, "post", "/lead/identity", {"cpf": cpf}, token)
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["cpf"] == cpf
    assert data["name"]  # identidade sintética do TEST_MODE
    assert data["sex"] in ("M", "F")
    assert data["birth_date"]
    assert data["photo"] is None
    assert Profile.objects.get(phone="5511987650010").cpf == cpf

    # idempotente: re-confirmar o MESMO cpf devolve a identidade gravada
    r2 = _json(client, "post", "/lead/identity", {"cpf": cpf}, token)
    assert r2.status_code == 200
    assert r2.json()["cpf"] == cpf


def test_identity_cpf_invalido_422(client, default_hub):
    token = _enter(client, "11987650011")
    r = _json(client, "post", "/lead/identity", {"cpf": "12345678900"}, token)
    assert r.status_code == 422
    assert r.json()["code"] == "CPF_INVALID"


def test_identity_cpf_conflict_notifica_e_purga(client, default_hub, monkeypatch):
    """CPF de OUTRA conta → 409 CPF_CONFLICT sem vazar dados do titular; a conta recém-criada
    da tentativa é APAGADA (libera o telefone) e o titular é notificado (data/hora/número)."""
    from notify.interface import send as notify_send
    from users.auth.models import User

    sent = []
    monkeypatch.setattr(notify_send, "send", lambda **kwargs: sent.append(kwargs) or str(uuid.uuid4()))

    cpf = _valid_cpf("111444777")
    token_dono = _enter(client, "11987650012")
    assert (
        _json(client, "post", "/lead/identity", {"cpf": cpf}, token_dono).status_code
        == 200
    )

    token_tentativa = _enter(client, "11987650013")
    attempt = User.objects.get(profile__phone="5511987650013")
    r = _json(client, "post", "/lead/identity", {"cpf": cpf}, token_tentativa)
    assert r.status_code == 409, r.content
    body = r.json()
    assert body["code"] == "CPF_CONFLICT"
    # sem vazar dados do titular (nem nome, nem telefone)
    assert "name" not in body

    # conta da tentativa purgada (cascade User → Profile/Lead/OTP) — telefone liberado
    assert not User.objects.filter(pk=attempt.pk).exists()
    # titular notificado com o número usado na tentativa
    notif = next(item for item in sent if item["caller"] == "auth.cpf_conflict")
    assert notif["phone"] == "5511987650012"
    assert "9876-50013" in notif["text"] or "98765-0013" in notif["text"]


def test_identity_nao_troca_cpf_ja_confirmado(client, default_hub):
    """Conta que JÁ confirmou um CPF não troca por aqui (suporte resolve) → 409 CPF_ALREADY_SET."""
    token = _enter(client, "11987650014")
    cpf1 = _valid_cpf("222333444")
    cpf2 = _valid_cpf("555666777")
    assert (
        _json(
            client, "post", "/lead/identity", {"cpf": cpf1}, token
        ).status_code
        == 200
    )
    r = _json(client, "post", "/lead/identity", {"cpf": cpf2}, token)
    assert r.status_code == 409
    assert r.json()["code"] == "CPF_ALREADY_SET"

    # Verificação física de camada de serviço (perfil imutável)
    from users.profiles import interface as profiles_iface
    from users.auth.models import User
    from users.exceptions import Conflict
    import pytest

    user = User.objects.filter(profile__cpf=cpf1).first()
    assert user is not None
    with pytest.raises(Conflict) as exc_info:
        profiles_iface.set_cpf_identity(user, cpf=cpf2)
    assert exc_info.value.code == "CPF_ALREADY_SET"


# ── [5] e-mail ───────────────────────────────────────────────────────────────


def test_email_grava_e_conflita(client, default_hub):
    token_a = _enter(client, "11987650020")
    r = _json(client, "post", "/lead/email", {"email": "Maria@Gmail.com"}, token_a)
    assert r.status_code == 200, r.content
    assert r.json()["email"] == "maria@gmail.com"  # normalizado
    assert r.json()["already_yours"] is False  # novo → front celebra "Excelente!"

    # o próprio e-mail de novo → idempotente, e o front troca a celebração
    # ("Perfeito, já é o seu e-mail") — por isso o flag no corpo
    r = _json(client, "post", "/lead/email", {"email": "maria@gmail.com"}, token_a)
    assert r.status_code == 200
    assert r.json()["already_yours"] is True

    # e-mail de OUTRA conta → 409 EMAIL_CONFLICT
    token_b = _enter(client, "11987650021")
    r = _json(client, "post", "/lead/email", {"email": "maria@gmail.com"}, token_b)
    assert r.status_code == 409
    assert r.json()["code"] == "EMAIL_CONFLICT"

    # formato inválido → 422 EMAIL_INVALID
    r = _json(client, "post", "/lead/email", {"email": "sem-arroba"}, token_b)
    assert r.status_code == 422
    assert r.json()["code"] == "EMAIL_INVALID"


# ── [6] checkout: por último, criável e TROCÁVEL ─────────────────────────────


def _complete_profile(client, token, cpf_seed: str, email: str) -> None:
    assert (
        _json(
            client, "post", "/lead/identity", {"cpf": _valid_cpf(cpf_seed)}, token
        ).status_code
        == 200
    )
    assert (
        _json(client, "post", "/lead/email", {"email": email}, token).status_code == 200
    )


def test_checkout_exige_perfil_completo(client, default_hub):
    """Pular identidade/e-mail e ir direto pro pagamento → 409 PROFILE_INCOMPLETE + missing."""
    token = _enter(client, "11987650030")
    r = _json(client, "post", "/lead/checkout", {"payment_method": "pix"}, token)
    assert r.status_code == 409, r.content
    body = r.json()
    assert body["code"] == "PROFILE_INCOMPLETE"
    assert set(body["missing_fields"]) == {"cpf", "email"}


def test_checkout_cria_e_troca_forma(client, default_hub):
    """PIX escolhido no passo 6 → checkout nasce; "Trocar" pro cartão → sessão RECRIADA
    (token/linha novos, método novo) e o `GET /lead/me` reflete a forma vigente do painel."""
    from users.roles.lead.models import Checkout

    token = _enter(client, "11987650031")
    _complete_profile(client, token, "333222111", "lead31@example.com")

    r = _json(client, "post", "/lead/checkout", {"payment_method": "pix"}, token)
    assert r.status_code == 200, r.content
    pix = r.json()
    assert pix["payment_method"] == "pix"
    assert pix["is_paid"] is False
    first = Checkout.objects.get(lead__user__profile__phone="5511987650031")
    first_token = first.short_token

    me = client.get(f"{BASE}/lead/me", HTTP_AUTHORIZATION=f"Bearer {token}").json()
    assert me["checkout"]["payment_method"] == "pix"

    # Trocar (painel → Planos → cartão): recria a sessão — método e token novos
    r = _json(client, "post", "/lead/checkout", {"payment_method": "card"}, token)
    assert r.status_code == 200, r.content
    card = r.json()
    assert card["payment_method"] == "credit_card"
    rows = Checkout.objects.filter(lead__user__profile__phone="5511987650031")
    assert rows.count() == 1  # a antiga morreu junto com a URL/link curto
    assert rows.first().short_token != first_token

    me = client.get(f"{BASE}/lead/me", HTTP_AUTHORIZATION=f"Bearer {token}").json()
    assert me["checkout"]["payment_method"] == "credit_card"


def test_checkout_pago_nao_troca(client, default_hub):
    """Pagamento confirmado → trocar a forma é 409 ALREADY_PAID (pago não se mexe)."""
    from users.roles.lead.models import Checkout, Lead

    token = _enter(client, "11987650032")
    _complete_profile(client, token, "444555666", "lead32@example.com")
    assert (
        _json(
            client, "post", "/lead/checkout", {"payment_method": "pix"}, token
        ).status_code
        == 200
    )
    lead = Lead.objects.get(user__profile__phone="5511987650032")
    Checkout.objects.filter(lead=lead).update(is_paid=True)
    lead.status = Lead.Status.PAID
    lead.save(update_fields=["status"])

    r = _json(client, "post", "/lead/checkout", {"payment_method": "card"}, token)
    assert r.status_code == 409
    assert r.json()["code"] == "ALREADY_PAID"


def test_funil_v2_fim_a_fim(client, default_hub):
    """O caminho canônico inteiro, na ordem do protótipo: telefone → OTP → CPF → e-mail →
    checkout PIX. Cada etapa avança e o painel (`/lead/me`) fecha com o funil completo."""
    token = _enter(client, "11987650040")
    _complete_profile(client, token, "987654321", "fim.a.fim@example.com")
    r = _json(client, "post", "/lead/checkout", {"payment_method": "pix"}, token)
    assert r.status_code == 200, r.content

    me = client.get(f"{BASE}/lead/me", HTTP_AUTHORIZATION=f"Bearer {token}").json()
    assert me["status"] == "pending"
    assert me["customer"]["cpf"] == _valid_cpf("987654321")
    assert me["customer"]["email"] == "fim.a.fim@example.com"
    assert me["checkout"]["payment_method"] == "pix"


def test_pricing_sem_ref_retorna_precos_padrao(client):
    """GET /pricing sem parâmetro retorna os preços de tabela, anchor_full e has_discount=False."""
    r = client.get(f"{BASE}/pricing")
    assert r.status_code == 200
    data = r.json()
    assert "pix" in data
    assert "card" in data
    assert "promo_pix" in data
    assert "promo_card" in data
    assert "anchor_full" in data
    assert data["has_discount"] is False
    assert data["promoter_name"] is None


def test_pricing_config_alterada_dispara_rebuild_astro(db):
    """Atualização de pricing via save_platform_config atualiza valores e dispara hook de rebuild."""
    from core import system_config, hooks

    dispatched = []

    def _mock_rebuild_hook(**kwargs):
        dispatched.append(kwargs)
        return True

    hooks.register("platform.pricing_updated", _mock_rebuild_hook)

    system_config.save_platform_config({
        "pricing": {
            "price_pix": "149",
            "price_card_cents": 14900,
            "anchor_full": "1800",
            "card_installments": 12,
        }
    })

    cfg = system_config.get_all_platform_config()
    assert cfg["pricing"]["price_pix"] == "149"
    assert cfg["pricing"]["anchor_full"] == "1800"
    assert len(dispatched) >= 1
    assert dispatched[-1]["pricing"]["price_pix"] == "149"


def test_pricing_com_ref_valido_retorna_desconto_e_nome(client, promoter):
    """GET /pricing?ref=... com promotor válido retorna has_discount=True e promoter_name."""
    r = client.get(f"{BASE}/pricing?ref={promoter.external_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["has_discount"] is True
    assert data["promoter_name"] == "Joana"
    assert data["promo_pix"] is not None
    assert data["promo_card"] is not None


# ── [6b] PIX: o link curto leva à página PIX PRÓPRIA (issue #158) ───────────
# O QR estático do Asaas (`/v3/pix/qrCodes/static`) NÃO tem fatura hospedada. Antes da #158 o
# `_fill_pix` gravava `checkout_url=None`, o `bind()` nunca rodava e cada clique no link curto
# tentava RECRIAR o QR com o mesmo `pid` → `payment_id_already_exists` → 503 eterno.

# PNG 1x1 válido (base64) — o `save_pix_qr_png` decodifica com validate=True.
_QR_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "AAH/q842iQAAAABJRU5ErkJggg=="
)
FRONT = "https://app.supletivo.test"
QR_ASAAS_ID = "QR1ASA"


@pytest.fixture
def asaas_qr_calls(monkeypatch, settings, tmp_path):
    """Stub só do TRANSPORTE do QR estático — o `create_pix_qr` de verdade roda.

    Assim a idempotência que o teste mede é a real (linha `Payment` reaproveitada), não a de um
    dublê. A lista devolvida acumula uma entrada por chamada ao gateway."""
    from core import system_config
    from integrations.bank.asaas import static_qr

    settings.MEDIA_ROOT = str(tmp_path)
    settings.FRONTEND_URL = FRONT
    system_config._SETTINGS_CACHE.pop("FRONTEND_URL", None)
    calls: list[dict] = []

    async def _key():
        return "chave-pix-de-teste"

    async def _create(pix_key, value, pid, description):
        calls.append(
            {"pix_key": pix_key, "value": value, "pid": pid, "description": description}
        )
        return {
            "id": QR_ASAAS_ID if len(calls) == 1 else f"QR{len(calls)}ASA",
            "payload": f"00020126580014br.gov.bcb.pix::{pid}",
            "encodedImage": _QR_PNG_B64,
        }

    monkeypatch.setattr(static_qr, "_fetch_pix_address_key", _key)
    monkeypatch.setattr(static_qr, "_create_qr_with_gateway", _create)
    return calls


def _pix_checkout(client, phone: str, cpf_seed: str, email: str):
    """Funil até o passo 6 com PIX escolhido. Devolve o `Checkout` (ainda SEM cobrança)."""
    from users.roles.lead.models import Checkout

    token = _enter(client, phone)
    _complete_profile(client, token, cpf_seed, email)
    r = _json(client, "post", "/lead/checkout", {"payment_method": "pix"}, token)
    assert r.status_code == 200, r.content
    return Checkout.objects.get(lead__user__profile__phone=f"55{phone}")


def test_pix_link_curto_redireciona_pra_pagina_pix_propria(
    client, default_hub, asaas_qr_calls
):
    """Build do PIX → `checkout_url` = NOSSA página (`FRONTEND_URL/pix/<token>`) + link curto 302."""
    from users.roles.lead import service as lead_service

    c = _pix_checkout(client, "11987650050", "111222333", "pix50@example.com")
    assert c.checkout_url is None  # nasce sem cobrança (build é async/lazy)

    lead_service.fill_checkout_from_provider(c)
    c.refresh_from_db()

    assert c.qrcode_payload  # copia-e-cola persistido
    assert c.provider_payment_id == f"lead_{c.lead.external_id.hex[:12]}_{c.pk}"
    assert c.checkout_url == f"{FRONT}/pix/{c.short_token}"

    r = client.get(f"/lead/checkout/{c.short_token}")
    assert r.status_code == 302, r.content
    assert r["Location"] == f"{FRONT}/pix/{c.short_token}"


def test_pix_clique_no_link_curto_constroi_e_repete_sem_recriar_cobranca(
    client, default_hub, asaas_qr_calls
):
    """O clique faz o build lazy e o SEGUNDO clique é idempotente: 302 de novo, gateway 1x só.

    Era o coração da #158: o 2o clique tentava reemitir o mesmo `pid` e o lead levava 503."""
    from integrations.bank.asaas.models import Payment

    c = _pix_checkout(client, "11987650051", "222333444", "pix51@example.com")

    first = client.get(f"/lead/checkout/{c.short_token}")
    assert first.status_code == 302, first.content
    assert first["Location"] == f"{FRONT}/pix/{c.short_token}"

    second = client.get(f"/lead/checkout/{c.short_token}")
    assert second.status_code == 302, second.content
    assert second["Location"] == first["Location"]

    assert len(asaas_qr_calls) == 1  # NÃO recriou a cobrança
    assert Payment.objects.filter(kind=Payment.Kind.STATIC_PIX_QR).count() == 1


def test_pix_build_repetido_reaproveita_o_qr_em_vez_de_estourar(
    client, default_hub, asaas_qr_calls
):
    """`create_pix_qr` com `payment_id` já emitido devolve a MESMA linha (sem tocar no gateway)."""
    from integrations.bank.asaas import static_qr

    c = _pix_checkout(client, "11987650052", "333444555", "pix52@example.com")
    pid = f"lead_{c.lead.external_id.hex[:12]}_{c.pk}"

    row = static_qr.create_pix_qr(amount=c.amount, payment_id=pid)
    again = static_qr.create_pix_qr(amount=c.amount, payment_id=pid)

    assert again.pk == row.pk
    assert len(asaas_qr_calls) == 1


def test_pix_cobra_o_valor_exato_do_plano(client, default_hub, asaas_qr_calls):
    """O QR estático leva o valor CHEIO do plano — sem piso, sem arredondar (não é fatura)."""
    from users.roles.lead import config
    from users.roles.lead import service as lead_service

    c = _pix_checkout(client, "11987650053", "444555777", "pix53@example.com")
    assert c.amount == config.price_pix()

    lead_service.fill_checkout_from_provider(c)
    c.refresh_from_db()

    assert asaas_qr_calls[0]["value"] == float(config.price_pix())
    assert c.amount == config.price_pix()


def test_pix_sem_frontend_url_serve_a_pagina_no_proprio_backend(
    client, default_hub, asaas_qr_calls, settings
):
    """Sem `FRONTEND_URL` o link curto NÃO pode virar 503: o Django serve a página PIX mínima."""
    from core import system_config

    settings.FRONTEND_URL = ""
    system_config._SETTINGS_CACHE.pop("FRONTEND_URL", None)

    c = _pix_checkout(client, "11987650054", "555666888", "pix54@example.com")
    r = client.get(f"/lead/checkout/{c.short_token}")

    assert r.status_code == 200, r.content
    c.refresh_from_db()
    body = r.content.decode()
    assert c.qrcode_payload in body
    assert "PIX" in body


def test_pix_endpoint_publico_devolve_o_qr_pelo_token(
    client, default_hub, asaas_qr_calls
):
    """`GET /lead/pix/<token>` (sem login) devolve valor + copia-e-cola + PNG relativo."""
    from users.roles.lead import service as lead_service

    c = _pix_checkout(client, "11987650055", "666777999", "pix55@example.com")
    lead_service.fill_checkout_from_provider(c)
    c.refresh_from_db()

    r = client.get(f"{BASE}/lead/pix/{c.short_token}")
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["amount"] == str(c.amount)
    assert data["is_paid"] is False
    assert data["qrcode_payload"] == c.qrcode_payload
    # RELATIVO (same-origin no front — o CSP do app só aceita img-src 'self').
    assert data["qrcode_image"].startswith("/")
    assert c.provider_payment_id in data["qrcode_image"]

    assert client.get(f"{BASE}/lead/pix/naoexiste").status_code == 404


def test_pix_webhook_casa_pelo_pix_qr_code_id_e_paga_o_lead(
    client, default_hub, asaas_qr_calls
):
    """No QR estático o Asaas CRIA a cobrança sozinho: sem o nosso `externalReference`, só com
    `pixQrCodeId` (= id do QR). A conciliação tem que casar por ele, senão o lead nunca paga."""
    from integrations.bank.asaas import webhooks
    from users.roles.lead import service as lead_service
    from users.roles.lead.models import Lead

    c = _pix_checkout(client, "11987650056", "777888111", "pix56@example.com")
    lead_service.fill_checkout_from_provider(c)
    c.refresh_from_db()
    assert asaas_qr_calls, "o build tinha que ter chamado o gateway"

    webhooks.handle_event(
        {
            "event": "PAYMENT_RECEIVED",
            "payment": {
                "id": "pay_gerado_pelo_asaas",
                "externalReference": None,  # a cobrança automática NÃO carrega o nosso pid
                "pixQrCodeId": QR_ASAAS_ID,
                "value": float(c.amount),
                "billingType": "PIX",
                "transactionReceiptUrl": "https://asaas.test/recibo/1",
            },
        }
    )

    c.refresh_from_db()
    assert c.is_paid is True
    assert c.receipt_url == "https://asaas.test/recibo/1"
    assert Lead.objects.get(pk=c.lead_id).status == Lead.Status.PAID


def test_pix_checkout_legado_com_url_nula_se_recupera_sozinho(
    client, default_hub, asaas_qr_calls
):
    """O caso de PRODUÇÃO da #158: linha antiga com QR já emitido e `checkout_url` NULO.

    É o estado exato do token que estava em 503 eterno — o QR existia, mas o `bind()` nunca
    rodou e cada clique tentava reemitir o mesmo `pid`. O link tem que voltar a funcionar SOZINHO,
    sem checkout novo e SEM tocar no gateway (nenhuma cobrança nova)."""
    from users.roles.lead import service as lead_service

    c = _pix_checkout(client, "11987650057", "888999222", "pix57@example.com")
    lead_service.fill_checkout_from_provider(c)
    c.refresh_from_db()
    assert len(asaas_qr_calls) == 1

    # Rebobina pro estado do bug: QR/pid persistidos, URL nula, cache do link curto vazio.
    from django.core.cache import cache
    from users.roles.lead.checkout_links import _PREFIX
    from users.roles.lead.models import Checkout

    Checkout.objects.filter(pk=c.pk).update(checkout_url=None)
    cache.delete(_PREFIX + c.short_token)
    c.refresh_from_db()
    assert c.checkout_url is None
    assert c.qrcode_payload  # o QR continua lá — é o que salva o link

    r = client.get(f"/lead/checkout/{c.short_token}")

    assert r.status_code == 302, r.content  # não é mais 503
    assert r["Location"] == f"{FRONT}/pix/{c.short_token}"
    assert len(asaas_qr_calls) == 1, "não pode emitir cobrança nova pra curar o link"
    c.refresh_from_db()
    assert c.checkout_url == f"{FRONT}/pix/{c.short_token}"  # curou a linha de vez


def test_pix_checkout_orfao_reaproveita_a_cobranca_ja_emitida_no_asaas(
    client, default_hub, asaas_qr_calls
):
    """Variante do legado: o `Payment` foi emitido no Asaas mas o `Checkout` ficou sem o QR.

    O build lazy roda de novo e `create_pix_qr` REAPROVEITA a linha do `pid` colidido em vez de
    estourar `payment_id_already_exists` — o lead sai do 503 e o Asaas não ganha cobrança nova."""
    from integrations.bank.asaas.models import Payment
    from users.roles.lead.models import Checkout

    c = _pix_checkout(client, "11987650058", "999222333", "pix58@example.com")
    pid = f"lead_{c.lead.external_id.hex[:12]}_{c.pk}"

    # Cobrança já existe no Asaas/no nosso Payment; o Checkout não sabe (build morreu no meio).
    from integrations.bank.asaas import static_qr

    emitted = static_qr.create_pix_qr(amount=c.amount, payment_id=pid)
    assert len(asaas_qr_calls) == 1
    Checkout.objects.filter(pk=c.pk).update(
        checkout_url=None, provider_payment_id=None, qrcode_payload=None
    )

    r = client.get(f"/lead/checkout/{c.short_token}")

    assert r.status_code == 302, r.content
    assert r["Location"] == f"{FRONT}/pix/{c.short_token}"
    assert len(asaas_qr_calls) == 1, "reaproveitou — nada de cobrança nova"
    assert Payment.objects.filter(payment_id=pid).count() == 1
    c.refresh_from_db()
    assert c.provider_payment_id == pid
    assert c.qrcode_payload == emitted.qrcode_payload
