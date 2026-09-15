"""Testes de HAPPY PATH E2E do funil do aluno (Lead v2 -> Pagamento -> Matrícula -> Aluno Ativo).

Cobertura da Jornada Completa:
1.  Check de telefone novo (/auth/check) -> auto-captura de User + Profile + Lead
2.  Login via OTP (/auth/login) -> emissão de Access Token (role lead)
3.  Confirmação de CPF (/lead/identity) -> validação de dados
4.  Confirmação de E-mail (/lead/email) -> gravação e normalização
5.  Geração de Checkout (/lead/checkout) -> PIX gerado
6.  Simulação de liquidação de pagamento Asaas -> transição para Enrollment (status RG)
7.  Upload de fotos do RG (front e back) (/enrollment/documents/rg/photo/{slot})
8.  Preenchimento de dados do RG (/enrollment/documents/rg PATCH) -> avanço para ADDRESS
9.  Definição de CEP e endereço residencial (/enrollment/address POST/PATCH)
10. Upload de Comprovante de Residência (/enrollment/address/proof) e aprovação
11. Preenchimento de histórico escolar (/enrollment/education) -> avanço para SELFIE
12. Upload de Selfie e assinatura eletrônica do contrato (/enrollment/selfie)
13. Homologação/Conclusão pelo Coordenador (conclude) -> promoção para Student
14. Consulta de Aluno Ativo (/student/me) com dados e plataforma provisionados
"""

from __future__ import annotations

import io
import json
import uuid
from decimal import Decimal
import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from PIL import Image

from finance.models import PaymentRequest
from hub.models import Hub
from users.address.models import Address
from users.auth.jwt.service import issue
from users.auth.models import User
from users.documents import service as documents
from users.roles import _address_proof, _document_ai as doc_ai, _selfie, interface as roles
from users.roles.enrollment import service as enrollment_iface
from users.roles.enrollment.models import Enrollment
from users.roles.lead import service as lead_iface
from users.roles.lead.models import Checkout
from users.roles.student.models import Student


BASE = "/api/v1/clients"
OTP = "000000"


def _valid_cpf(seed9: str) -> str:
    assert len(seed9) == 9 and seed9.isdigit()

    def dv(digits: str) -> str:
        weights = range(len(digits) + 1, 1, -1)
        total = sum(int(d) * w for d, w in zip(digits, weights))
        rest = (total * 10) % 11
        return "0" if rest == 10 else str(rest)

    d1 = dv(seed9)
    return seed9 + d1 + dv(seed9 + d1)


def _png(color: str = "white", size: tuple[int, int] = (16, 16)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return SimpleUploadedFile(
        f"doc_{color}_{uuid.uuid4().hex[:6]}.png", buffer.getvalue(), content_type="image/png"
    )


@pytest.fixture
def default_hub(db):
    """Hub padrão com coordenador para todo o fluxo de captação e matrícula."""
    coord = User.objects.create_user(external_id=uuid.uuid4())
    roles.assign(coord, "candidate")
    roles.promote(coord, "promoter")
    roles.grant(coord, "coordinator")
    address = Address.objects.create(
        city="Curitiba",
        state="PR",
        street="Rua XV de Novembro",
        number="200",
        neighborhood="Centro",
        zipcode="80020000",
    )
    return Hub.objects.create(
        address=address,
        brand="standard",
        coordinator=coord,
        is_default=True,
    )


@pytest.fixture
def temp_media_storage(monkeypatch, tmp_path):
    from core import media

    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(documents, "default_storage", storage)
    monkeypatch.setattr(media, "default_storage", storage)
    return storage


# ---------------------------------------------------------------------------
# Jornada Happy Path E2E Completa
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_complete_journey_e2e(client: Client, default_hub: Hub, temp_media_storage, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))

    # [Passo 1] Check de telefone novo (captura)
    phone = "41991234567"
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
    )
    assert check_res.status_code == 200
    check_data = check_res.json()
    assert check_data["created"] is True
    assert check_data["otp_sent"] is True
    user_ext_id = check_data["external_id"]

    # [Passo 2] Login por OTP
    login_res = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": user_ext_id, "otp": OTP}),
        content_type="application/json",
    )
    assert login_res.status_code == 200
    lead_token = login_res.json()["access_token"]

    # [Passo 3] Identidade (CPF)
    cpf = _valid_cpf("987654321")
    id_res = client.post(
        f"{BASE}/lead/identity",
        data=json.dumps({"cpf": cpf}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {lead_token}",
    )
    assert id_res.status_code == 200
    assert id_res.json()["cpf"] == cpf

    # [Passo 4] E-mail
    email = "aluno.completo@gmail.com"
    email_res = client.post(
        f"{BASE}/lead/email",
        data=json.dumps({"email": email}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {lead_token}",
    )
    assert email_res.status_code == 200
    assert email_res.json()["email"] == email

    # [Passo 5] Checkout (PIX)
    checkout_res = client.post(
        f"{BASE}/lead/checkout",
        data=json.dumps({"payment_method": "pix"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {lead_token}",
    )
    assert checkout_res.status_code == 200
    assert checkout_res.json()["payment_method"] == "pix"

    # [Passo 6] Liquidação simulada de pagamento Asaas -> Criação de Matrícula (Enrollment)
    checkout = Checkout.objects.get(lead__user__external_id=user_ext_id)
    checkout.provider_payment_id = "pay_student_e2e_01"
    checkout.save(update_fields=["provider_payment_id"])
    assert lead_iface.mark_paid(provider=checkout.provider, provider_payment_id="pay_student_e2e_01")

    # Atualiza token com a nova role 'enrollment'
    user = User.objects.get(external_id=user_ext_id)
    enrollment_token = issue(user_ext_id, roles.active_roles(user))["access_token"]

    # [Passo 7] Wizard Matrícula: GET /enrollment/me inicial (status RG)
    enr_me = client.get(
        f"{BASE}/enrollment/me",
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    ).json()
    assert enr_me["status"] == "rg"

    # [Passo 8] Upload de Fotos do RG (Frente e Verso)
    file_front = _png("green")
    res_front = client.post(
        f"{BASE}/enrollment/documents/rg/photo/front",
        data={"file": file_front},
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert res_front.status_code == 200

    file_back = _png("blue")
    res_back = client.post(
        f"{BASE}/enrollment/documents/rg/photo/back",
        data={"file": file_back},
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert res_back.status_code == 200

    # Simula aprovação de IA do RG
    rg_doc = documents.get_rg(user_ext_id)
    rg_doc.validation_status = doc_ai.APPROVED
    rg_doc.save(update_fields=["validation_status"])

    # [Passo 9] PATCH do RG (Número e dados de filiação) -> Avança para ADDRESS
    patch_rg_res = client.patch(
        f"{BASE}/enrollment/documents/rg",
        data=json.dumps({
            "number": "123456789",
            "issuing_agency": "SSP/PR",
            "issue_date": "2020-01-01",
            "mother_name": "Maria Silva",
            "father_name": "Jose Silva",
            "birthplace": "Curitiba/PR",
            "marital_status": "solteiro",
            "nationality": "brasileira",
        }),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert patch_rg_res.status_code == 200
    assert patch_rg_res.json()["status"] == "address"

    # [Passo 10] Endereço Residencial (CEP + Dados complementares)
    client.post(
        f"{BASE}/enrollment/address",
        data=json.dumps({"cep": "80020000"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    addr_patch_res = client.patch(
        f"{BASE}/enrollment/address",
        data=json.dumps({
            "street": "Rua das Flores",
            "number": "123",
            "neighborhood": "Centro",
            "city": "Curitiba",
            "state": "PR",
        }),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert addr_patch_res.status_code == 200

    # [Passo 11] Comprovante de Residência e Aprovação
    proof_file = _png("yellow")
    proof_res = client.post(
        f"{BASE}/enrollment/address/proof",
        data={"file": proof_file},
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert proof_res.status_code == 200

    ap_doc = documents.get_address_proof(user_ext_id)
    ap_doc.validation_status = _address_proof.APPROVED
    ap_doc.save(update_fields=["validation_status"])
    enr = enrollment_iface.get_for_user_external_id(user_ext_id)
    enrollment_iface._advance_address(enr, user_ext_id)

    # Verifica avanço para EDUCATION
    enr_edu_check = client.get(
        f"{BASE}/enrollment/me",
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    ).json()
    assert enr_edu_check["status"] == "education"

    # [Passo 12] Escolaridade
    edu_res = client.post(
        f"{BASE}/enrollment/education",
        data=json.dumps({
            "level": "fundamental",
            "grade": 8,
            "completed": True,
            "last_school": "Colégio Estadual do Paraná",
            "city": "Curitiba",
            "state": "PR",
        }),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert edu_res.status_code == 200
    assert edu_res.json()["status"] == "selfie"

    # [Passo 13] Selfie (Assinatura Eletrônica)
    selfie_file = _png("purple")
    selfie_res = client.post(
        f"{BASE}/enrollment/selfie",
        data={"file": selfie_file},
        HTTP_AUTHORIZATION=f"Bearer {enrollment_token}",
    )
    assert selfie_res.status_code == 200

    # [Passo 14] Conclusão pelo Coordenador (Taxa de Polo + Conclude)
    enr = enrollment_iface.get_for_user_external_id(user_ext_id)
    enr.selfie_status = _selfie.APPROVED
    enr.selfie_verified = True
    enr.save(update_fields=["selfie_status", "selfie_verified"])
    enrollment_iface._advance_to_release(enr)

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
        coordinator=default_hub.coordinator,
        platform_login=f"aluno_e2e_{uuid.uuid4().hex[:6]}",
        platform_password="senha_forte_123",
    )

    # [Passo 15] Verificação do Aluno Ativo (/student/me)
    user.refresh_from_db()
    assert "student" in roles.active_roles(user)
    student_token = issue(user_ext_id, roles.active_roles(user))["access_token"]

    student_res = client.get(
        f"{BASE}/student/me",
        HTTP_AUTHORIZATION=f"Bearer {student_token}",
    )
    assert student_res.status_code == 200
    student_data = student_res.json()
    assert student_data["status"] == "awaiting_documents"
    assert student_data["hub_external_id"] == str(default_hub.external_id)
    assert student_data["platform"]["login"] is not None
    assert student_data["platform"]["password"] == "senha_forte_123"
