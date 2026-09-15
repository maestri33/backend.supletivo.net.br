import pytest

from hub import interface as hub_iface
from users.address import interface as address_iface
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.models import UserRole

pytestmark = pytest.mark.django_db


def _create_promoter_user(phone="5511988887777"):
    user = User.objects.create_user()
    profiles.create(user=user, cpf=None, phone=phone, name="Promotor Teste")
    UserRole.objects.create(user=user, role="promoter")
    return user


def test_create_hub_requires_coordinator():
    with pytest.raises(hub_iface.HubError) as exc_info:
        hub_iface.create_hub(brand="wyden", coordinator_external_id=None)
    assert "coordinator_required" in str(exc_info.value)


def test_create_hub_requires_promoter_role():
    non_promoter = User.objects.create_user()
    profiles.create(user=non_promoter, cpf=None, phone="5511911112222", name="Aluno Teste")

    with pytest.raises(hub_iface.HubError) as exc_info:
        hub_iface.create_hub(
            brand="wyden",
            coordinator_external_id=str(non_promoter.external_id),
        )
    assert "coordinator_not_promoter" in str(exc_info.value)


def test_create_hub_success_with_promoter_and_address():
    promoter = _create_promoter_user()

    hub = hub_iface.create_hub(
        brand="wyden",
        coordinator_external_id=str(promoter.external_id),
        street="Av. Santos Dumont",
        number="1500",
        complement="Torre Sul",
        neighborhood="Aldeota",
        city="Fortaleza",
        state="CE",
    )

    assert hub.brand == "wyden"
    assert hub.coordinator_id == promoter.id
    assert "coordinator" in roles.active_roles(promoter)
    assert hub.address is not None
    assert hub.address.street == "Av. Santos Dumont"
    assert hub.address.number == "1500"
    assert hub.address.city == "Fortaleza"
    assert hub.address.state == "CE"


def test_create_hub_with_existing_address_id():
    promoter = _create_promoter_user("5511977776666")
    addr = address_iface.create_empty()
    addr.street = "Rua Existente"
    addr.city = "Recife"
    addr.state = "PE"
    addr.save()

    hub = hub_iface.create_hub(
        brand="estacio",
        coordinator_external_id=str(promoter.external_id),
        address_id=addr.pk,
    )

    assert hub.address_id == addr.pk
    assert hub.address.street == "Rua Existente"
    assert hub.coordinator_id == promoter.id
