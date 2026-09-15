import pytest
from decimal import Decimal

from hub import interface as hub_iface
from users.auth.models import User
from users.documents.models import Document, RG
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment.models import Enrollment
from users.roles.lead.models import Lead
from users.roles.promoter.models import Promoter
from users.roles.training.models import Material, MaterialAssignment, Submission

from users.roles.models import UserRole

pytestmark = pytest.mark.django_db


def test_staff_document_reviews_and_dossier():
    staff_user = User.objects.create_user()
    staff_user.is_superuser = True
    staff_user.save()

    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511988881111", name="Promotor Hub")
    UserRole.objects.create(user=promoter, role="promoter")
    hub = hub_iface.create_hub(brand="wyden", coordinator_external_id=str(promoter.external_id))

    student_user = User.objects.create_user()
    profiles.create(user=student_user, cpf=None, phone="5511922223333", name="Aluno Dossiê")
    doc_root = Document.objects.create(user=student_user)
    rg = RG.objects.create(
        document=doc_root,
        number="12345678",
        validation_status="review",
        validation_result={"reason": "Foto com reflexo"},
    )
    enr = Enrollment.objects.create(
        user=student_user,
        promoter=promoter,
        hub=hub,
        status=Enrollment.Status.RG,
        selfie_status="review",
    )

    from api.staff.routers.documents import get_user_dossier, list_global_document_reviews

    class DummyRequest:
        auth = staff_user

    req = DummyRequest()
    reviews = list_global_document_reviews(req)
    assert len(reviews) >= 1
    assert any(r["user_external_id"] == str(student_user.external_id) for r in reviews)

    dossier = get_user_dossier(req, str(student_user.external_id))
    assert dossier["profile"]["name"] == "Aluno Dossiê"
    assert dossier["document_data"]["number"] == "12345678"
    assert dossier["document_data"]["validation_status"] == "review"


def test_staff_network_tree():
    staff_user = User.objects.create_user()
    staff_user.is_superuser = True
    staff_user.save()

    coord = User.objects.create_user()
    profiles.create(user=coord, cpf=None, phone="5511988882222", name="Coordenador Geral")
    UserRole.objects.create(user=coord, role="promoter")
    hub = hub_iface.create_hub(brand="estacio", coordinator_external_id=str(coord.external_id))

    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511988883333", name="Promotor Rede")
    prom_obj = Promoter.objects.create(user=promoter, hub=hub, status="active")

    lead_user = User.objects.create_user()
    profiles.create(user=lead_user, cpf=None, phone="5511944445555", name="Lead Pago")
    Lead.objects.create(user=lead_user, promoter=promoter, status=Lead.Status.PAID)

    from api.staff.routers.network import get_network_tree

    class DummyRequest:
        auth = staff_user

    tree = get_network_tree(DummyRequest())
    assert len(tree) >= 1
    hub_data = next((h for h in tree if h["hub_external_id"] == str(hub.external_id)), None)
    assert hub_data is not None
    assert hub_data["metrics"]["total_leads"] == 1
    assert hub_data["metrics"]["total_paid"] == 1
    assert hub_data["metrics"]["conversion_rate"] == 100.0


def test_staff_training_unlock():
    staff_user = User.objects.create_user()
    staff_user.is_superuser = True
    staff_user.save()

    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511988884444", name="Promotor Travado")
    UserRole.objects.create(user=promoter, role="promoter")
    roles.grant(promoter, "training")

    mat = Material.objects.create(title="Matéria 1", question="Q1?", expected_answer="R1")
    MaterialAssignment.objects.create(user=promoter, material=mat, status=MaterialAssignment.Status.PENDING)

    from api.staff.routers.training import unlock_promoter_training

    class DummyRequest:
        auth = staff_user

    res = unlock_promoter_training(DummyRequest(), str(promoter.external_id))
    assert "desbloqueado com sucesso" in res["detail"]

    # Trava removida
    assert "training" not in roles.active_roles(promoter)
    assert MaterialAssignment.objects.filter(user=promoter, status="pending").count() == 0


