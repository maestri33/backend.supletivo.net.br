import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from hub import interface as hub_iface
from users.auth.models import User
from users.documents.models import Document, RG
from users.profiles import interface as profiles
from users.roles.models import UserRole
from users.roles.candidate.models import Candidate
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment import service as enrollment_service
from users.roles.lead.models import Lead, Checkout
from users.roles.lead import service as lead_service
from users.roles.promoter.models import Promoter
from users.roles.student.models import Student
from users.roles.training.models import Material, MaterialAssignment, Submission
from users.roles.training import service as training_service
from finance.models import PaymentRequest

pytestmark = pytest.mark.django_db


def test_document_reviews_batch_optimization():
    """Testa que list_global_document_reviews não faz consultas N+1 ao iterar matrículas e candidatos."""
    staff_user = User.objects.create_user()
    staff_user.is_superuser = True
    staff_user.save()

    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511977771000", name="Promotor Base")
    UserRole.objects.create(user=promoter, role="promoter")
    hub = hub_iface.create_hub(brand="wyden", coordinator_external_id=str(promoter.external_id))

    # Cria 5 matrículas com documentos
    for i in range(5):
        u = User.objects.create_user()
        profiles.create(user=u, cpf=None, phone=f"551197777100{i+1}", name=f"Aluno {i}")
        doc = Document.objects.create(user=u)
        RG.objects.create(document=doc, number=f"RG{i}", validation_status="review")
        Enrollment.objects.create(
            user=u,
            promoter=promoter,
            hub=hub,
            status=Enrollment.Status.RG,
            selfie_status="review",
        )

    # Cria 3 candidatos
    for i in range(3):
        u = User.objects.create_user()
        profiles.create(user=u, cpf=None, phone=f"551197777200{i}", name=f"Cand {i}")
        Candidate.objects.create(user=u, hub=hub, status=Candidate.Status.STARTED, selfie_status="review")

    from api.staff.routers.documents import list_global_document_reviews

    class DummyRequest:
        auth = staff_user

    req = DummyRequest()

    with CaptureQueriesContext(connection) as ctx:
        reviews = list_global_document_reviews(req)

    # Verifica que retornou todos os itens esperados
    assert len(reviews) >= 8
    # Total de queries é O(1) e não cresce com N (máximo 8 queries para carregar tudo em batch)
    assert len(ctx.captured_queries) <= 8


def test_network_tree_batch_optimization():
    """Testa que get_network_tree agrega métricas e perfis em lote sem N+1."""
    staff_user = User.objects.create_user()
    staff_user.is_superuser = True
    staff_user.save()

    coord1 = User.objects.create_user()
    profiles.create(user=coord1, cpf=None, phone="5511966661001", name="Coord 1")
    UserRole.objects.create(user=coord1, role="promoter")
    hub1 = hub_iface.create_hub(brand="wyden", coordinator_external_id=str(coord1.external_id))

    coord2 = User.objects.create_user()
    profiles.create(user=coord2, cpf=None, phone="5511966661002", name="Coord 2")
    UserRole.objects.create(user=coord2, role="promoter")
    hub2 = hub_iface.create_hub(brand="estacio", coordinator_external_id=str(coord2.external_id))

    # Cria 4 promotores com leads
    for i in range(4):
        p_user = User.objects.create_user()
        profiles.create(user=p_user, cpf=None, phone=f"551196666200{i}", name=f"Promoter {i}")
        UserRole.objects.create(user=p_user, role="promoter")
        h = hub1 if i < 2 else hub2
        Promoter.objects.create(user=p_user, hub=h, status="active")

        # 3 leads por promotor
        for j in range(3):
            l_user = User.objects.create_user()
            profiles.create(user=l_user, cpf=None, phone=f"5511966663{i}{j}", name=f"Lead {i}-{j}")
            status = Lead.Status.PAID if j == 0 else Lead.Status.PENDING
            Lead.objects.create(user=l_user, promoter=p_user, status=status)

    from api.staff.routers.network import get_network_tree

    class DummyRequest:
        auth = staff_user

    with CaptureQueriesContext(connection) as ctx:
        tree = get_network_tree(DummyRequest())

    assert len(tree) >= 2
    # Deve executar no máximo 6 queries (1 Auth check + Hubs, Promoters, Profiles, Lead aggregation, Student aggregation)
    assert len(ctx.captured_queries) <= 6


def test_enrollment_batch_fee_facts_optimization():
    """Testa que list_for_hub carrega as taxas em lote com batch_fee_facts."""
    coord = User.objects.create_user()
    profiles.create(user=coord, cpf=None, phone="5511955551000", name="Coord Hub Fees")
    UserRole.objects.create(user=coord, role="promoter")
    hub = hub_iface.create_hub(brand="wyden", coordinator_external_id=str(coord.external_id))

    enrollments = []
    for i in range(4):
        u = User.objects.create_user()
        profiles.create(user=u, cpf=None, phone=f"551195555100{i+1}", name=f"Aluno Fee {i}")
        enr = Enrollment.objects.create(
            user=u,
            promoter=coord,
            hub=hub,
            status=Enrollment.Status.AWAITING_RELEASE,
        )
        enrollments.append(enr)

        # Cria PaymentRequest para a primeira parcela
        PaymentRequest.objects.create(
            external_reference=f"fee_enr_{enr.external_id}_now",
            kind=PaymentRequest.Kind.FEE,
            method=PaymentRequest.Method.PIX_QRCODE,
            amount=100.0,
            status=PaymentRequest.Status.PAID,
            source_type=PaymentRequest.SourceType.ENROLLMENT,
            source_external_id=enr.external_id,
        )

    # Executa list_for_hub
    with CaptureQueriesContext(connection) as ctx:
        items = enrollment_service.list_for_hub(hub=hub)

    assert len(items) == 4
    for it in items:
        assert it["fees"]["first_paid"] is True
        assert it["fees"]["second_scheduled"] is False

    # Deve executar no máximo 3 queries: Enrollment select, Profile map, PaymentRequest batch
    assert len(ctx.captured_queries) <= 3


def test_training_assigned_materials_optimization():
    """Testa que assigned_materials carrega as submissões em batch."""
    user = User.objects.create_user()
    profiles.create(user=user, cpf=None, phone="5511944441000", name="Promotor Training")

    for i in range(5):
        mat = Material.objects.create(
            title=f"Matéria {i}",
            question=f"Pergunta {i}?",
            expected_answer=f"Resposta {i}",
            order=i,
            active=True,
        )
        MaterialAssignment.objects.create(user=user, material=mat, status=MaterialAssignment.Status.APPROVED)
        # Cria 2 submissões por matéria (a mais recente deve ser escolhida)
        Submission.objects.create(user=user, material=mat, status="failed", grade=4)
        Submission.objects.create(user=user, material=mat, status="approved", grade=10)

    with CaptureQueriesContext(connection) as ctx:
        result = training_service.assigned_materials(str(user.external_id))

    assert len(result) == 5
    for item in result:
        assert item["submission_status"] == "approved"
        assert item["grade"] == "10.0"

    # User lookup + MaterialAssignment query + 1 bulk Submission query = 3 queries
    assert len(ctx.captured_queries) <= 3


def test_lead_to_dict_profile_map_support():
    """Testa que lead_to_dict com select_related e profile pré-carregado não executa queries adicionais."""
    u = User.objects.create_user()
    p = profiles.create(user=u, cpf=None, phone="5511933331000", name="Lead Batch Test")
    prom = User.objects.create_user()
    lead_obj = Lead.objects.create(user=u, promoter=prom, status=Lead.Status.PENDING)
    Checkout.objects.create(
        lead=lead_obj,
        payment_method=Checkout.Method.PIX,
        provider=Checkout.Provider.ASAAS,
        amount=150.0,
    )

    lead = Lead.objects.select_related("user", "promoter", "checkout").get(id=lead_obj.id)

    # Chamada passando profile explicitamente para lead pré-carregado: 0 queries
    with CaptureQueriesContext(connection) as ctx:
        res = lead_service.lead_to_dict(lead, profile=p)

    assert res["name"] == "Lead Batch Test"
    assert len(ctx.captured_queries) == 0
