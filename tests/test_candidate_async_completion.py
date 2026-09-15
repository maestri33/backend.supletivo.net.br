from __future__ import annotations

import uuid

import pytest


def _candidate_with_documents():
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.documents import service as documents
    from users.profiles.models import Profile
    from users.roles.candidate.models import Candidate

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.create(
        address=Address.objects.create(city="Ponta Grossa", state="PR"),
        brand="test",
        coordinator=coordinator,
        is_default=True,
    )
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(
        user=user,
        cpf=str(uuid.uuid4().int)[:11],
        phone=str(uuid.uuid4().int)[:13],
        address=Address.objects.create(),
    )
    documents.create_empty(user)
    candidate = Candidate.objects.create(
        user=user,
        hub=hub,
        status=Candidate.Status.SELFIE,
        doc_type=Candidate.DocType.RG,
        selfie_verified=True,
    )
    return candidate


@pytest.mark.django_db
def test_selfie_nao_promove_enquanto_documento_esta_pendente(monkeypatch):
    from users.documents import service as documents
    from users.roles.candidate import service
    from users.roles.candidate.models import Candidate

    candidate = _candidate_with_documents()
    rg = documents.get_doc_sub(str(candidate.user.external_id), "rg")
    proof = documents.get_address_proof(str(candidate.user.external_id))
    rg.validation_status = "pending"
    rg.save(update_fields=["validation_status"])
    proof.validation_status = "approved"
    proof.save(update_fields=["validation_status"])
    promoted = []
    monkeypatch.setattr(
        service, "_promote_to_promoter", lambda cand: promoted.append(cand.pk)
    )

    service._complete_candidate(candidate)

    candidate.refresh_from_db()
    assert candidate.status == Candidate.Status.COMPLETED
    assert promoted == []


@pytest.mark.django_db
def test_promove_quando_analises_assincronas_terminam(monkeypatch):
    from users.documents import service as documents
    from users.roles.candidate import service

    candidate = _candidate_with_documents()
    candidate.status = "completed"
    candidate.save(update_fields=["status"])
    rg = documents.get_doc_sub(str(candidate.user.external_id), "rg")
    proof = documents.get_address_proof(str(candidate.user.external_id))
    rg.validation_status = "approved"
    rg.save(update_fields=["validation_status"])
    proof.validation_status = "approved"
    proof.save(update_fields=["validation_status"])
    promoted = []
    monkeypatch.setattr(
        service, "_promote_to_promoter", lambda cand: promoted.append(cand.pk)
    )

    service._complete_candidate(candidate)

    assert promoted == [candidate.pk]


def test_comprovante_pode_ser_a_fonte_inicial_do_endereco():
    from users.roles import _address_proof

    matches, reason = _address_proof._address_matches(
        {"zip": "84050-360", "city": "Ponta Grossa"}, None
    )

    assert matches is True
    assert "preenchido a partir do comprovante" in reason
