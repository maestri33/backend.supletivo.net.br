import pytest

from users.address import service as addresses
from users.profiles import interface as profiles

pytestmark = pytest.mark.django_db


def _user_with_empty_address():
    from users.auth.models import User

    user = User.objects.create_user()
    profile = profiles.create(user=user, cpf=None, phone="5511999999999")
    profiles.attach_address(profile, addresses.create_empty())
    return user


def test_fill_empty_normaliza_cep_extraido_com_hifen():
    user = _user_with_empty_address()

    address = addresses.fill_empty(
        external_id=str(user.external_id),
        zipcode="84050-360",
        street="RUA ATAULFO ALVES",
        number="770",
        complement="SB 4",
        neighborhood="ESTRELA",
        city="PONTA GROSSA",
        state="PR",
    )

    assert address.zipcode == "84050360"
    assert address.street == "RUA ATAULFO ALVES"
    assert address.number == "770"
    assert address.complement == "SB 4"
    assert address.neighborhood == "ESTRELA"
    assert address.city == "PONTA GROSSA"
    assert address.state == "PR"
