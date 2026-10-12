import json
import uuid

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def _student_at_education():
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.documents import service as documents
    from users.profiles.models import Profile
    from users.roles.enrollment.models import Enrollment

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.create(address=Address.objects.create(), coordinator=coordinator)
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, address=Address.objects.create(), name="Aluno")
    documents.create_empty(user)
    enr = Enrollment.objects.create(user=user, promoter=coordinator, hub=hub, status="education")
    return user, enr


def _student_token(user):
    from users.auth.jwt import service as jwt
    return jwt.issue(str(user.external_id), ["enrollment"])["access_token"]


def test_student_api_requires_declaration_and_blocks_completed_third_year():
    user, _ = _student_at_education()
    client = Client()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_student_token(user)}"}
    payload = {"level": "medio", "grade": 3, "completed": False, "last_school": "", "city": "Ponta Grossa", "state": "PR"}
    missing = client.post("/api/v1/clients/enrollment/education", data=json.dumps(payload), content_type="application/json", **headers)
    assert missing.status_code == 422
    assert missing.json()["detail"][0]["loc"][-1] == "declaration_accepted"
    payload["declaration_accepted"] = True
    completed = {**payload, "completed": True}
    rejected = client.post("/api/v1/clients/enrollment/education", data=json.dumps(completed), content_type="application/json", **headers)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "EDUCATION_ALREADY_COMPLETED"


def test_student_declaration_is_audited_after_valid_submission():
    user, enr = _student_at_education()
    client = Client()
    payload = {"level": "medio", "grade": 3, "completed": False, "last_school": "", "city": "Ponta Grossa", "state": "PR", "declaration_accepted": True}
    response = client.post("/api/v1/clients/enrollment/education", data=json.dumps(payload), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {_student_token(user)}", HTTP_USER_AGENT="education-test")
    assert response.status_code == 200
    enr.refresh_from_db()
    assert enr.education_declaration_accepted is True
    assert enr.education_declaration_version == "education-v1"
    assert enr.education_declaration_at is not None


def test_ibge_cache_rejects_city_from_another_state():
    from integrations.tools.ibge.service import existe
    assert existe("Ponta Grossa", "PR") is not None
    assert existe("Ponta Grossa", "SP") is None


def _candidate_at_education():
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.documents import service as documents
    from users.profiles.models import Profile
    from users.roles.candidate.models import Candidate

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.create(address=Address.objects.create(), coordinator=coordinator)
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, address=Address.objects.create(), name="Promotor")
    documents.create_empty(user)
    candidate = Candidate.objects.create(user=user, hub=hub, status="education")
    return user, candidate


def _candidate_token(user):
    from users.auth.jwt import service as jwt
    return jwt.issue(str(user.external_id), ["candidate"])["access_token"]


def test_candidate_api_requires_declaration_and_accepts_superior_with_ibge_location():
    user, candidate = _candidate_at_education()
    client = Client()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_candidate_token(user)}"}
    base = {
        "level": "superior",
        "completed": True,
        "qualification": "graduacao",
        "education_status": "completed",
        "city": " Ponta Grossa ",
        "state": "pr",
        "year": 2020,
    }
    missing = client.post(
        "/api/v1/collaborators/candidate/education",
        data=json.dumps(base),
        content_type="application/json",
        **headers,
    )
    assert missing.status_code == 422
    assert missing.json()["detail"][0]["loc"][-1] == "declaration_accepted"

    response = client.post(
        "/api/v1/collaborators/candidate/education",
        data=json.dumps({**base, "declaration_accepted": True}),
        content_type="application/json",
        HTTP_USER_AGENT="education-candidate-test",
        **headers,
    )
    assert response.status_code == 200
    assert response.json()["profile"]["education_state"] == "PR"
    candidate.refresh_from_db()
    assert candidate.education_declaration_accepted is True
    assert candidate.education_declaration_version == "education-v1"
    assert candidate.education_declaration_at is not None
