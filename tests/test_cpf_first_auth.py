import pytest
from users.auth import service as auth_iface
from users.profiles import interface as profiles
from users.auth.models import User

@pytest.mark.django_db
def test_cpf_check_existing_user():
    user = User.objects.create_user()
    profile = profiles.create(
        user=user,
        cpf="11144477735",
        phone="5511999990000",
        name="Maestri User",
    )
    
    result = auth_iface.check(cpf="111.444.777-35")
    assert result["found"] is True
    assert result["registered"] is True
    assert result["external_id"] == str(user.external_id)
    assert result["name"] == "Maestri User"
    assert result["masked_phone"] == "(11) 99999-0000"
    assert result["otp_sent"] is True

@pytest.mark.django_db
def test_cpf_check_new_user_synthetic_lookup():
    result = auth_iface.check(cpf="22233344455")
    assert result["found"] is False
    assert result["registered"] is False
    assert result["is_valid"] is True
    assert result["name"] is not None
    assert result["birth_date"] is not None
    assert result["sex"] in ("M", "F")

@pytest.mark.django_db
def test_register_adds_role_to_existing_cpf_user():
    # Registration with same CPF links to existing user instead of failing
    reg1 = auth_iface.register(role="lead", phone="5511911112222", cpf="33344455566")
    user1_id = reg1["external_id"]

    reg2 = auth_iface.register(role="candidate", phone="5511911112222", cpf="33344455566")
    assert reg2["external_id"] == user1_id # Same user ID linked!
