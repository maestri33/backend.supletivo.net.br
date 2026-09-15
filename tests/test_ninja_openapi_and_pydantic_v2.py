"""Testes de conformidade com Django Ninja OpenAPI, Pydantic v2 e Padronização de Schemas."""

import pytest
from django.test import Client

from api.staff import schemas as staff_schemas
from users.auth.jwt import service as jwt_service
from users.auth.models import User


@pytest.mark.django_db
def test_all_ninja_apis_generate_valid_openapi_json():
    """Valida que todos os 6 grupos de APIs Ninja geram especificação OpenAPI 3 válida sem erros."""
    client = Client()
    apis = [
        "/api/v1/clients/openapi.json",
        "/api/v1/collaborators/openapi.json",
        "/api/v1/leadership/openapi.json",
        "/api/v1/staff/openapi.json",
        "/api/v1/tools/openapi.json",
        "/api/v1/health/openapi.json",
    ]
    for url in apis:
        resp = client.get(url)
        assert resp.status_code == 200, f"Falha ao gerar OpenAPI para {url}: {resp.content}"
        data = resp.json()
        assert "openapi" in data or "swagger" in data
        assert "paths" in data
        assert len(data["paths"]) > 0


def test_staff_schemas_pydantic_v2_and_from_attributes():
    """Garante que os schemas de saída do Staff configuram model_config['from_attributes']=True do Pydantic v2."""
    orm_schemas = [
        staff_schemas.HubOut,
        staff_schemas.PromoterOut,
        staff_schemas.CoordinatorOut,
        staff_schemas.DocumentReviewOut,
        staff_schemas.UserDossierOut,
        staff_schemas.StaffCommissionOut,
        staff_schemas.StaffPaymentRequestOut,
        staff_schemas.ManualPaymentOut,
        staff_schemas.StaffMaterialOut,
        staff_schemas.NetworkTreeHubOut,
        staff_schemas.NotifyTemplateOut,
        staff_schemas.AiCallLogOut,
        staff_schemas.ValidationCheckLogOut,
        staff_schemas.TrainingSubmissionOut,
        staff_schemas.StaffLeadOut,
        staff_schemas.StaffEnrollmentOut,
        staff_schemas.StaffStudentOut,
        staff_schemas.StaffUserOut,
    ]
    for schema_cls in orm_schemas:
        cfg = getattr(schema_cls, "model_config", None)
        assert cfg is not None, f"{schema_cls.__name__} não possui model_config"
        assert cfg.get("from_attributes") is True, (
            f"{schema_cls.__name__} deve ter from_attributes=True no model_config"
        )


@pytest.mark.django_db
def test_jwt_claims_carry_synthetic_staff_for_superuser():
    """Superuser recebe a claim sintética `staff` (emissão E rotação); usuário comum não."""
    superuser = User.objects.create_superuser(password="superpass")
    plain = User.objects.create_user()

    su_claims = jwt_service.decode(jwt_service.issue(str(superuser.external_id), [])["access_token"])
    assert "staff" in su_claims["roles"]

    rotated = jwt_service.refresh(jwt_service.issue(str(superuser.external_id), [])["refresh_token"])
    assert "staff" in jwt_service.decode(rotated["access_token"])["roles"]

    plain_claims = jwt_service.decode(jwt_service.issue(str(plain.external_id), ["promoter"])["access_token"])
    assert "staff" not in plain_claims["roles"]


@pytest.mark.django_db
def test_filter_schema_query_handling_via_ninja_client():
    """Testa que os FilterSchemas filtram corretamente as requisições HTTP."""
    superuser = User.objects.create_superuser(password="superpass")
    tokens = jwt_service.issue(str(superuser.external_id), [])
    headers = {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}
    client = Client()

    # Test GET /leads com query param de filtro
    resp = client.get("/api/v1/staff/leads?status=registered", **headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Test GET /training/submissions com query params de filtro
    resp = client.get("/api/v1/staff/training/submissions?status=approved", **headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Test GET /logs/checks com query params de filtro
    resp = client.get("/api/v1/staff/logs/checks?scope=auth", **headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.django_db
def test_public_healthz_endpoint_schema():
    """Testa se o endpoint /healthz responde com o schema HealthzOut correto."""
    client = Client()
    resp = client.get("/api/v1/health/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "db" in data
    assert "migrations_pending" in data


@pytest.mark.django_db
def test_post_creation_endpoints_return_201():
    """Testa se endpoints de criação retornam HTTP 201 Created."""
    from users.profiles import interface as profiles
    from users.roles.models import UserRole

    superuser = User.objects.create_superuser(password="superpass")
    tokens = jwt_service.issue(str(superuser.external_id), [])
    headers = {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}
    client = Client()

    # Promotor para coordenar o polo
    promoter_user = User.objects.create_user()
    profiles.create(user=promoter_user, cpf=None, phone="5511988887777", name="Promotor Coordenador")
    UserRole.objects.create(user=promoter_user, role="promoter")

    # POST /hubs
    payload = {
        "brand": "wyden",
        "coordinator_external_id": str(promoter_user.external_id),
        "cep": "01001000",
        "street": "Praça da Sé",
        "number": "100",
        "city": "São Paulo",
        "state": "SP",
    }
    resp = client.post("/api/v1/staff/hubs", data=payload, content_type="application/json", **headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["brand"] == "wyden"

    # POST /training/materials
    mat_payload = {
        "title": "Treinamento 201",
        "content_type": "text",
        "body_md": "Conteudo de teste",
        "question": "Pergunta 1",
        "expected_answer": "Resposta 1",
    }
    resp = client.post("/api/v1/staff/training/materials", data=mat_payload, content_type="application/json", **headers)
    assert resp.status_code == 201
    mat_data = resp.json()
    assert mat_data["title"] == "Treinamento 201"


@pytest.mark.django_db
def test_veteran_me_schema_contract(monkeypatch):
    """Testa se /veteran/me adere ao schema VeteranMeOut."""
    import uuid
    import api.clients as clients
    from api.clients.routers.student import veteran_me

    vet_uuid = str(uuid.uuid4())

    class DummyReq:
        auth = type("Auth", (), {"external_id": vet_uuid})()

    user = User.objects.create_user()
    user.external_id = uuid.UUID(vet_uuid)
    user.save()

    req = DummyReq()
    monkeypatch.setattr(clients, "_veteran_guard", lambda r: vet_uuid)
    monkeypatch.setattr(
        clients.student_iface,
        "veteran_detail",
        lambda *, user_external_id: {
            "user": {"external_id": user_external_id},
            "documents": [],
            "diploma": None,
            "pendencies": [],
        },
    )

    res = veteran_me(req)
    assert "user" in res
    assert "documents" in res
    assert "diploma" in res
    assert "enrollment" in res

