"""Testes para validação de PIX do Promotor, Comissões Manuais, Antecipação e Auto-Teste do Staff."""

from decimal import Decimal
import uuid
import pytest
from django.test import override_settings

from finance.interface import commissions as finance_closing
from finance.models import Commission, PaymentRequest
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.models import UserRole
from users.roles.promoter import service as promoter_iface
from hub.models import Hub


@pytest.fixture
def promoter_user(db):
    from users.address import interface as address_iface

    user = User.objects.create_user(password="secret123")
    profile = profiles.create(
        user=user,
        cpf="09126367939",
        phone="5543996648750",
        name="Victor Maestri",
    )
    addr = address_iface.create_empty()
    hub = Hub.objects.create(brand="standard", coordinator=user, is_default=True, address=addr)
    promoter = promoter_iface.create_promoter(user=user, hub=hub)
    UserRole.objects.create(user=user, role="promoter")
    UserRole.objects.create(user=user, role="staff")
    return user, promoter, profile, hub


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_set_promoter_pix_success(promoter_user):
    user, promoter, profile, _ = promoter_user
    res = promoter_iface.set_promoter_pix(
        promoter=promoter,
        key="09126367939",
        key_type="CPF",
    )
    assert res["pix_key"] == "09126367939"
    assert res["key_type"] == "CPF"
    assert res["validated"] is True

    # Verifica se persistiu no profile
    p = profiles.get(user)
    assert p.pix_key == "09126367939"


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_set_promoter_pix_empty_key_fails(promoter_user):
    _, promoter, _, _ = promoter_user
    with pytest.raises(Exception):
        promoter_iface.set_promoter_pix(
            promoter=promoter,
            key="   ",
        )


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_credit_manual_commission(promoter_user):
    user, _, _, _ = promoter_user
    comm = finance_closing.credit_manual_commission(
        payee=user,
        amount=Decimal("150.00"),
        description="Bônus de campanha extraordinária",
        role="promoter",
    )
    assert comm.amount == Decimal("150.00")
    assert comm.source_type == Commission.Source.MANUAL
    assert comm.status == Commission.Status.PENDING
    assert comm.payee == user


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_advance_user_payout(promoter_user):
    user, _, profile, _ = promoter_user
    profile.pix_key = "09126367939"
    profile.save(update_fields=["pix_key"])

    # Cria 2 comissões pendentes
    finance_closing.credit_manual_commission(payee=user, amount=Decimal("50.00"))
    finance_closing.credit_manual_commission(payee=user, amount=Decimal("75.00"))

    res = finance_closing.advance_user_payout(user=user, immediate_submit=False)
    assert res["amount"] == "125.00"
    assert res["commissions_count"] == 2
    assert res["status"] == PaymentRequest.Status.QUEUED

    # Comissões devem estar PROCESSED
    assert Commission.objects.filter(payee=user, status=Commission.Status.PROCESSED).count() == 2
    assert Commission.objects.filter(payee=user, status=Commission.Status.PENDING).count() == 0


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_advance_user_payout_without_pending_fails(promoter_user):
    user, _, _, _ = promoter_user
    with pytest.raises(ValueError, match="no_pending_commissions"):
        finance_closing.advance_user_payout(user=user)


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_promoter_me_includes_pix_data(promoter_user):
    user, promoter, profile, _ = promoter_user
    profile.pix_key = "09126367939"
    profile.save(update_fields=["pix_key"])

    data = promoter_iface.to_dict(promoter)
    assert data["pix_key"] == "09126367939"
    assert data["name"] == "Victor Maestri"
    assert data["phone"] == "5543996648750"
    assert "hub_brand" in data


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_http_collaborator_promoter_pix_endpoints(client, promoter_user):
    from users.auth.jwt import service as jwt_service
    user, _, _, _ = promoter_user
    token = jwt_service.issue(str(user.external_id), ["promoter"])["access_token"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # PUT /api/v1/collaborators/promoter/pix
    res = client.put(
        "/api/v1/collaborators/promoter/pix",
        data={"pix_key": "09126367939", "key_type": "CPF"},
        content_type="application/json",
        **headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["pix_key"] == "09126367939"
    assert data["validated"] is True


@pytest.mark.django_db
@override_settings(TEST_EXTERNAL_ADAPTERS=True)
def test_http_staff_manual_commission_and_advance(client, promoter_user):
    from users.auth.jwt import service as jwt_service
    user, _, profile, _ = promoter_user
    user.is_superuser = True
    user.is_staff = True
    user.save()
    profile.pix_key = "09126367939"
    profile.save()

    token = jwt_service.issue(str(user.external_id), ["staff", "promoter"])["access_token"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # 1. Cria comissão avulsa
    res = client.post(
        "/api/v1/staff/finance/commissions/manual",
        data={
            "user_external_id": str(user.external_id),
            "amount": "200.00",
            "description": "Comissão avulsa teste",
            "role": "promoter",
        },
        content_type="application/json",
        **headers,
    )
    assert res.status_code == 201
    c_data = res.json()
    assert c_data["amount"] == "200.00"

    # 2. Antecipa comissões
    res2 = client.post(
        f"/api/v1/staff/finance/commissions/advance/{user.external_id}",
        content_type="application/json",
        **headers,
    )
    assert res2.status_code == 200
    adv_data = res2.json()
    assert adv_data["amount"] == "200.00"
    assert adv_data["commissions_count"] == 1


