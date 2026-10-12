"""Suíte canônica do fluxo de comprovante de endereço (aluno e promotor).

Cobre:
1. Match por CPF no comprovante (aprovação direta com prioridade máxima).
2. Sem CPF: nomes iguais (aprova).
3. Sem CPF: nomes parecidos / dúvida da IA (review / conferência humana).
4. Sem CPF: nomes divergentes (needs_kinship / exige indicação de vínculo).
5. População automática no banco de dados (Address).
6. Endpoints HTTP: POST, PUT (reinício) e GET (status isolado) para Aluno e Promotor.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt import service as jwt
from users.auth.models import User
from users.documents import service as documents
from users.profiles.models import Profile
from users.roles import _address_proof as ap
from users.roles.candidate.models import Candidate
from users.roles.enrollment.models import Enrollment
from users.roles.models import UserRole

pytestmark = pytest.mark.django_db


def _png():
    output = BytesIO()
    Image.new("RGB", (32, 32), (80, 120, 160)).save(output, format="PNG")
    return output.getvalue()


class _AddrMock:
    def __init__(self, zipcode="01310100", street="Avenida Paulista", city="São Paulo"):
        self.zipcode = zipcode
        self.street = street
        self.city = city
        self.number = "1000"
        self.state = "SP"


def _run_ai_mock(extracted, *, vision=("approved", "ok"), user_cpf="12345678901", holder_name="Maria Silva"):
    with (
        patch("users.roles.student._document_ai.check_student_document_photo", return_value=vision),
        patch("users.roles.student._document_ai.ocr_image", return_value="ocr text"),
        patch("users.roles.student._document_ai.extract_student_document", return_value=extracted),
    ):
        return ap.run_validation(
            b"fake",
            address=_AddrMock(),
            holder_name=holder_name,
            user_cpf=user_cpf,
            caller="test",
        )


# ── 1. TESTES UNITÁRIOS DA MÁQUINA DE DECISÃO ────────────────────────────────


def test_cpf_no_comprovante_bate_com_cadastro_aprova_direto():
    """Se o CPF do comprovante for igual ao do usuário, APROVA direto com prioridade máxima."""
    status, payload = _run_ai_mock(
        {
            "holder_cpf": "123.456.789-01",
            "holder_name": "Nome Totalmente Estranho",  # Mesmo se o nome parecer estranho
            "name_match": "nao",
            "zip": "01310100",
            "city": "São Paulo",
        },
        user_cpf="12345678901",
    )
    assert status == ap.APPROVED
    assert payload.get("cpf_match") is True
    assert "CPF" in payload.get("reason", "")


def test_sem_cpf_nomes_iguais_aprova():
    """Se não houver CPF, mas o nome do titular for igual, APROVA."""
    status, payload = _run_ai_mock(
        {
            "holder_cpf": None,
            "holder_name": "Maria Silva",
            "name_match": "sim",
            "name_reason": "Mesmo titular",
            "zip": "01310100",
            "city": "São Paulo",
        },
        user_cpf="12345678901",
        holder_name="Maria Silva",
    )
    assert status == ap.APPROVED
    assert "validado" in payload.get("reason", "").lower() or "titular" in payload.get("reason", "").lower()


def test_sem_cpf_nomes_parecidos_ou_duvida_vai_pra_review():
    """Se não houver CPF e a IA estiver em dúvida nos nomes, envia para revisão humana."""
    status, payload = _run_ai_mock(
        {
            "holder_cpf": None,
            "holder_name": "M. Silva",
            "name_match": "duvida",
            "name_reason": "Abreviação incompleta",
            "zip": "01310100",
            "city": "São Paulo",
        },
        user_cpf="12345678901",
        holder_name="Maria Silva",
    )
    assert status == ap.REVIEW
    assert "confirmar o titular" in payload.get("reason", "").lower()


def test_sem_cpf_nomes_diferentes_pede_parentesco_com_motivo_divergente():
    """Se não houver CPF e o nome for diferente, cai em needs_kinship informando nome divergente."""
    status, payload = _run_ai_mock(
        {
            "holder_cpf": None,
            "holder_name": "João Pereira",
            "name_match": "nao",
            "name_reason": "Outra pessoa",
            "zip": "01310100",
            "city": "São Paulo",
        },
        user_cpf="12345678901",
        holder_name="Maria Silva",
    )
    assert status == ap.NEEDS_KINSHIP
    assert payload.get("kinship_kind") == "justify"
    assert "divergente" in payload.get("reason", "").lower()


def test_popula_endereco_no_db_ao_aprovar():
    """Quando aprovado, preenche os campos do modelo Address via _fill_address_from_extracted."""
    user = User.objects.create_user()
    addr = Address.objects.create(zipcode="", street="", number="", city="", state="")
    Profile.objects.create(user=user, phone="5511999990099", address=addr, name="Teste Aluno")

    extracted = {
        "street": "Rua das Palmeiras",
        "number": "500",
        "complement": "Apto 12",
        "neighborhood": "Jardins",
        "city": "Londrina",
        "state": "PR",
        "zip": "86000-000",
    }
    ap._fill_address_from_extracted(str(user.external_id), extracted, caller="test")

    addr.refresh_from_db()
    assert addr.street == "Rua das Palmeiras"
    assert addr.number == "500"
    assert addr.complement == "Apto 12"
    assert addr.neighborhood == "Jardins"
    assert addr.city == "Londrina"
    assert addr.state == "PR"
    assert addr.zipcode == "86000000"


# ── 2. TESTES HTTP: ROTAS DO ALUNO (ENROLLMENT) ───────────────────────────────


@pytest.fixture
def enrollment_user():
    address = Address.objects.create()
    promoter_address = Address.objects.create()
    hub = Hub.objects.create(address=address, brand="standard")
    user = User.objects.create_user()
    promoter_user = User.objects.create_user()
    Profile.objects.create(user=user, phone="5511999990002", address=address, name="Aluno Teste", cpf="07461638947")
    Profile.objects.create(user=promoter_user, phone="5511999990005", address=promoter_address, name="Promotor Resp", cpf="09126367939")
    documents.create_empty(user)
    UserRole.objects.create(user=user, role="enrollment")
    UserRole.objects.create(user=promoter_user, role="promoter")
    enr = Enrollment.objects.create(user=user, promoter=promoter_user, hub=hub, status=Enrollment.Status.ADDRESS)
    return enr


def _student_headers(enr):
    tokens = jwt.issue(str(enr.user.external_id), ["enrollment"])
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}


def test_student_address_proof_get_returns_status(client, enrollment_user):
    """GET /enrollment/address/proof retorna status e dados do comprovante."""
    proof = documents.get_address_proof(str(enrollment_user.user.external_id))
    proof.validation_status = "needs_kinship"
    proof.photo = "documents/test/proof.jpg"
    proof.validation_result = {"holder_name": "Carlos Silva", "kinship_kind": "confirm"}
    proof.save(update_fields=["validation_status", "photo", "validation_result"])

    response = client.get("/api/v1/clients/enrollment/address/proof", **_student_headers(enrollment_user))
    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["status"] == "needs_kinship"
    assert data["needs_kinship"] is True
    assert data["holder_name"] == "Carlos Silva"


def test_student_address_proof_put_replaces_and_restarts(client, enrollment_user, monkeypatch):
    """PUT /enrollment/address/proof substitui o comprovante e reinicia a análise assíncrona."""
    queued = []
    monkeypatch.setattr("core.tasks.async_task", lambda name, pk: queued.append((name, pk)))

    # Simula comprovante anterior rejeitado com trava
    proof = documents.get_address_proof(str(enrollment_user.user.external_id))
    proof.validation_status = "rejected"
    proof.validation_result = {"needs_new_proof": True}
    proof.save(update_fields=["validation_status", "validation_result"])

    from django.test.client import MULTIPART_CONTENT

    file = SimpleUploadedFile("novo_comprovante.png", _png(), content_type="image/png")
    payload = client._encode_data({"file": file}, MULTIPART_CONTENT)
    response = client.put(
        "/api/v1/clients/enrollment/address/proof",
        payload,
        content_type=MULTIPART_CONTENT,
        **_student_headers(enrollment_user),
    )
    assert response.status_code == 200
    proof.refresh_from_db()
    assert proof.validation_status == "pending"
    assert proof.validation_result == {}  # Limpou o resultado anterior e a flag de trava
    assert queued == [("users.roles.enrollment.tasks.validate_address_proof", enrollment_user.pk)]


# ── 3. TESTES HTTP: ROTAS DO PROMOTOR (CANDIDATE) ─────────────────────────────


@pytest.fixture
def candidate_user():
    address = Address.objects.create()
    hub = Hub.objects.create(address=address, brand="standard")
    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="5511999990003", address=address, name="Promotor Teste", cpf="09126367939")
    documents.create_empty(user)
    UserRole.objects.create(user=user, role="candidate")
    cand = Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.ADDRESS)
    return cand


def _promoter_headers(cand):
    tokens = jwt.issue(str(cand.user.external_id), ["candidate"])
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}


def test_candidate_address_proof_get_and_aliases(client, candidate_user):
    """GET /candidate/documents/address-proof e alias /candidate/address/proof retornam o status."""
    proof = documents.get_address_proof(str(candidate_user.user.external_id))
    proof.validation_status = "approved"
    proof.photo = "documents/test/proof_promoter.jpg"
    proof.save(update_fields=["validation_status", "photo"])

    # Rota principal
    res1 = client.get("/api/v1/collaborators/candidate/documents/address-proof", **_promoter_headers(candidate_user))
    assert res1.status_code == 200
    assert res1.json()["status"] == "approved"

    # Alias padronizado
    res2 = client.get("/api/v1/collaborators/candidate/address/proof", **_promoter_headers(candidate_user))
    assert res2.status_code == 200
    assert res2.json()["status"] == "approved"


def test_candidate_address_proof_put_replaces_and_restarts(client, candidate_user, monkeypatch):
    """PUT /candidate/documents/address-proof e alias reiniciam análise."""
    from django.test.client import MULTIPART_CONTENT

    queued = []
    monkeypatch.setattr("core.tasks.async_task", lambda name, pk: queued.append((name, pk)))

    file = SimpleUploadedFile("proof2.png", _png(), content_type="image/png")
    payload = client._encode_data({"file": file}, MULTIPART_CONTENT)
    response = client.put(
        "/api/v1/collaborators/candidate/address/proof",
        payload,
        content_type=MULTIPART_CONTENT,
        **_promoter_headers(candidate_user),
    )
    assert response.status_code == 200
    proof = documents.get_address_proof(str(candidate_user.user.external_id))
    assert proof.validation_status == "pending"
    assert queued == [("users.roles.candidate.tasks.validate_address_proof", candidate_user.pk)]
