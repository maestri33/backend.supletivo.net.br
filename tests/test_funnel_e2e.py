"""Funil do ALUNO fim-a-fim (regressão de CI): register → login(OTP) → pagar → RG → endereço →
comprovante(+aprovar) → escolaridade → selfie → `student/me`. In-process, via Django test Client,
exercitando o stack HTTP real (URLs, middleware, exception handlers, auth JWT do Ninja).

FALHA ALTO no passo EXATO em que o funil quebra: a cada etapa consulta `GET /enrollment/me` e afirma
que o `status` do wizard avançou. Se um passo não avança (ex.: "preso em address"), o assert estoura ali.

Fronteira HTTP × interface (deliberada, cada uma comentada onde acontece):
  - **HTTP-testado** (endpoint real + asserção de estado): register, check, login, upload de RG,
    PATCH do RG, POST/PATCH de endereço, upload do comprovante, escolaridade, selfie, student/me.
  - **interface-driven** (portão EXTERNO/HUMANO/HARDWARE que NÃO roda no CI, dirigido pelo módulo
    com comentário): (a) confirmação do pagamento (webhook Asaas), (b) veredito da IA que aprova o
    RG e o comprovante (o provider de IA não existe no CI e a task Django-Q não roda no teste),
    (c) biometria da selfie (InsightFace indisponível) + conclusão do coordenador (taxa + credenciais).

NÃO enfraquece nenhum portão de produção: os vereditos da IA/biometria são setados no MESMO estado
terminal que a task escreveria, e a conclusão chama o `conclude` REAL (só a taxa é semeada).
"""

from __future__ import annotations

import io
import json
import uuid
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

pytestmark = pytest.mark.django_db

BASE = "/api/v1/clients"

# CPF: só formato é validado (11 dígitos, não todos iguais); em TEST_MODE a identidade é sintética.
CPF = "12345678901"
PHONE = "11987654321"
EMAIL = "aluno.e2e@example.com"
OTP = (
    "000000"  # TEST_MODE_OTP_CODE — fixo no modo anti-prod (users/auth/otp/service.py)
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _png() -> SimpleUploadedFile:
    """PNG minúsculo VÁLIDO (o upload faz decode real — arquivo renomeado não passa)."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return SimpleUploadedFile("doc.png", buf.getvalue(), content_type="image/png")


def _json(client, method, path, body, token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return getattr(client, method)(
        f"{BASE}{path}",
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )


def _me_status(client, token) -> dict:
    r = client.get(f"{BASE}/enrollment/me", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200, f"/enrollment/me falhou: {r.status_code} {r.content}"
    return r.json()


# ── portões interface-driven (EXTERNO/HUMANO/HARDWARE — comentados na origem) ─
def _simulate_payment(user_external_id: str) -> None:
    """Confirma o pagamento do lead — MODELA o webhook do Asaas (gateway externo).

    O register cria o Checkout LOCAL sem `provider_payment_id` (o gateway só o preenche numa task
    async que não roda no teste). Aqui preenchemos o id e chamamos `lead_iface.mark_paid` — o MESMO
    ponto que o handler do webhook do Asaas chama — promovendo lead→enrollment via `create_from_lead`.
    """
    from users.roles.lead import service as lead_iface
    from users.roles.lead.models import Checkout

    checkout = Checkout.objects.get(lead__user__external_id=user_external_id)
    checkout.provider_payment_id = "pay_e2e_0001"
    checkout.save(update_fields=["provider_payment_id"])
    assert lead_iface.mark_paid(
        provider=checkout.provider, provider_payment_id="pay_e2e_0001"
    ), "mark_paid não casou o checkout do lead"


def _approve_rg(user_external_id: str) -> None:
    """MODELA o pipeline de IA aprovando a foto do RG (visão → OCR → extração).

    A validação real roda numa task Django-Q com provider de IA — nenhum dos dois existe no CI.
    Setamos o MESMO estado terminal que a task escreveria (validation_status=approved); o `number`
    e os campos de perfil o aluno completa via PATCH HTTP (o funil real também aceita digitação)."""
    from users.documents import service as documents_iface
    from users.roles import _document_ai as doc_ai

    rg = documents_iface.get_rg(user_external_id)
    rg.validation_status = doc_ai.APPROVED
    rg.save(update_fields=["validation_status"])


def _approve_address_proof(user_external_id: str) -> None:
    """MODELA a IA/staff aprovando o comprovante de residência.

    Espelha exatamente `enrollment.run_address_proof_validation`: seta o veredito aprovado (que a task
    de IA escreveria) e re-roda o avanço do wizard que a task chama em seguida (`_advance_address`).
    NÃO enfraquece o portão KYC — só substitui a IA/humano indisponíveis no CI."""
    from users.documents import service as documents_iface
    from users.roles import _address_proof
    from users.roles.enrollment import service as enrollment_iface

    ap = documents_iface.get_address_proof(user_external_id)
    ap.validation_status = _address_proof.APPROVED
    ap.save(update_fields=["validation_status"])
    enr = enrollment_iface.get_for_user_external_id(user_external_id)
    enrollment_iface._advance_address(enr, user_external_id)


def _coordinator_concludes(user_external_id: str, coordinator) -> None:
    """MODELA biometria da selfie + conclusão do coordenador (portão HUMANO/HARDWARE/finance).

    A biometria (InsightFace) não roda no CI; a taxa (2 parcelas PIX) e as credenciais da plataforma
    são ação do COORDENADOR, fora do controle do aluno. Setamos a selfie no estado aprovado (que a
    biometria escreveria) → AWAITING_RELEASE, semeamos as 2 fees (1ª paga / 2ª agendada) e chamamos o
    `conclude` REAL — a promoção enrollment→student (role + Student) é a lógica de produção, testada."""
    from django.utils import timezone

    from finance.models import PaymentRequest
    from users.roles import _selfie
    from users.roles.enrollment import service as enrollment_iface

    enr = enrollment_iface.get_for_user_external_id(user_external_id)
    # biometria passou → selfie aprovada → AWAITING_RELEASE (o que run_selfie_validation faria).
    enr.selfie_status = _selfie.APPROVED
    enr.selfie_verified = True
    enr.save(update_fields=["selfie_status", "selfie_verified"])
    enrollment_iface._advance_to_release(enr)

    # semeia os FATOS da taxa que o `conclude` exige (fee_facts): 1ª parcela paga + 2ª agendada.
    PaymentRequest.objects.create(
        external_reference=f"fee_enr_{enr.external_id}_now",
        kind=PaymentRequest.Kind.FEE,
        amount=Decimal("50.00"),
        status=PaymentRequest.Status.PAID,
    )
    PaymentRequest.objects.create(
        external_reference=f"fee_enr_{enr.external_id}_due",
        kind=PaymentRequest.Kind.FEE,
        amount=Decimal("50.00"),
        status=PaymentRequest.Status.QUEUED,
        scheduled_for=timezone.now(),
    )
    enrollment_iface.conclude(
        enrollment_external_id=str(enr.external_id),
        coordinator=coordinator,
        platform_login=f"aluno_{uuid.uuid4().hex[:8]}",
        platform_password="senha-plataforma",
    )


# ── fixtures ─────────────────────────────────────────────────────────────────
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


@pytest.fixture(autouse=True)
def _media_and_cep(monkeypatch, tmp_path):
    """MEDIA_ROOT em tmp (uploads gravam em disco) + ViaCEP mockado (serviço externo — sem rede)."""
    from django.conf import settings
    from users.address import service as address_service

    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        address_service,
        "_viacep",
        lambda cep: {
            "zipcode": "01310100",
            "street": "Avenida Paulista",
            "neighborhood": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
            "complement": "",
        },
    )


# ── o funil ──────────────────────────────────────────────────────────────────
def test_aluno_funnel_end_to_end(client, default_hub):
    coordinator = default_hub

    # 1) REGISTER (HTTP, auth=None) — cria lead + user + checkout.
    r = _json(
        client,
        "post",
        "/auth/register",
        {"cpf": CPF, "phone": PHONE, "email": EMAIL, "payment_method": "card"},
    )
    assert r.status_code == 201, f"register: {r.status_code} {r.content}"
    uid = r.json()["user_external_id"]

    # 2) CHECK (HTTP, auth=None) — vaza existência + dispara OTP fresco pro login.
    r = _json(client, "post", "/auth/check", {"cpf": CPF})
    assert r.status_code == 200 and r.json()["found"] is True, r.content
    assert r.json()["external_id"] == uid

    # 3) PAGAMENTO — interface-driven (webhook Asaas): promove lead→enrollment.
    #    (feito ANTES do login: o JWT é emitido com as roles ATIVAS; sem pagar, o token não teria a
    #    role `enrollment` e as rotas /enrollment/* dariam 403.)
    _simulate_payment(uid)

    # 4) LOGIN (HTTP, auth=None, OTP 000000) — JWT com todas as roles ativas (inclui enrollment).
    r = _json(client, "post", "/auth/login", {"external_id": uid, "otp": OTP})
    assert r.status_code == 200, f"login: {r.status_code} {r.content}"
    token = r.json()["access_token"]

    # matrícula nasce na etapa RG (documento primeiro — plan/13).
    assert _me_status(client, token)["status"] == "rg"

    # 5) RG — upload da foto (HTTP) → aprovação da IA (interface) → PATCH dos campos (HTTP) → ADDRESS.
    r = client.post(
        f"{BASE}/enrollment/documents/rg/photo/front",
        {"file": _png()},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert r.status_code == 200, f"upload rg: {r.status_code} {r.content}"
    _approve_rg(uid)  # interface: IA aprovou a foto do documento
    r = _json(
        client,
        "patch",
        "/enrollment/documents/rg",
        {
            "number": "12.345.678-9",
            "issuing_agency": "SSP-SP",
            "issue_date": "2015-06-01",
            "mother_name": "Maria da Silva",
            "father_name": "José da Silva",
            "birthplace": "São Paulo-SP",
            "marital_status": "solteiro",
            "nationality": "brasileira",
        },
        token,
    )
    assert r.status_code == 200, f"patch rg: {r.status_code} {r.content}"
    assert r.json()["status"] == "address", "RG completo não avançou pra ADDRESS"

    # 6) ENDEREÇO — POST só com CEP (HTTP, ViaCEP mockado) → falta o número.
    r = _json(client, "post", "/enrollment/address", {"cep": "01310100"}, token)
    assert r.status_code == 200, f"post address: {r.status_code} {r.content}"
    body = r.json()
    assert body["status"] == "address"
    assert body["address"]["missing_fields"] == ["number"], body["address"]

    # PATCH do número (HTTP) — endereço completo → avança pra EDUCATION (accept-first: a IA
    # do comprovante roda em background; rejeição vira ValidationBlock, não trava o wizard).
    r = _json(client, "patch", "/enrollment/address", {"number": "1000"}, token)
    assert r.status_code == 200 and r.json()["status"] == "education", (
        f"endereço completo não avançou pra EDUCATION: {r.content}"
    )

    # comprovante de residência — upload (HTTP) → enfileira validação async. O wizard já avançou;
    # a rejeição (se houver) cria um ValidationBlock que aparece no /me e o front mostra modal.
    r = client.post(
        f"{BASE}/enrollment/address/proof",
        {"file": _png()},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert r.status_code == 200, f"upload proof: {r.status_code} {r.content}"

    # aprovação do comprovante via interface (IA/staff) — best-effort; não afeta mais o avanço.
    _approve_address_proof(uid)

    # 7) ESCOLARIDADE (HTTP) → SELFIE.
    r = _json(
        client,
        "post",
        "/enrollment/education",
        {
            "level": "medio",
            "grade": 3,
            "completed": False,
            "last_school": "Escola Estadual Central",
            "city": "São Paulo",
            "state": "SP",
        },
        token,
    )
    assert r.status_code == 200, f"education: {r.status_code} {r.content}"
    assert r.json()["status"] == "selfie", "escolaridade não avançou pra SELFIE"

    # 8) SELFIE (HTTP) — a assinatura da matrícula. Exercita o contrato do endpoint: a foto é aceita,
    #    o aceite LGPD é gravado e a análise fica pendente (biometria roda em 2º plano).
    r = client.post(
        f"{BASE}/enrollment/selfie",
        {"file": _png()},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert r.status_code == 200, f"selfie: {r.status_code} {r.content}"
    body = r.json()
    assert body["status"] == "selfie"
    assert body["selfie"]["exists"] is True, body["selfie"]

    # 9) biometria + conclusão do coordenador — interface-driven → promove enrollment→student.
    _coordinator_concludes(uid, coordinator)

    # o JWT do login não carrega a role `student` recém-concedida. O login por OTP já foi HTTP-testado
    # acima; aqui re-emitimos o JWT com as roles atuais direto pelo serviço (evita a flakiness do
    # rate-limit do OTP ao disparar um 3º código em poucos segundos).
    from users.auth.jwt import service as jwt_service
    from users.auth.models import User
    from users.roles import interface as roles

    student = User.objects.get(external_id=uid)
    assert "student" in roles.active_roles(student), (
        "conclude não concedeu a role student"
    )
    student_token = jwt_service.issue(uid, roles.active_roles(student))["access_token"]

    # 10) TERMINAL — /student/me 200: o aluno chegou ao fim do funil.
    r = client.get(f"{BASE}/student/me", HTTP_AUTHORIZATION=f"Bearer {student_token}")
    assert r.status_code == 200, f"student/me: {r.status_code} {r.content}"
    assert r.json()["external_id"], "student/me sem external_id"
