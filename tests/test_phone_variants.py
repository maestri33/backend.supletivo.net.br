"""Lookup de telefone tolerante ao 9º dígito.

O número é gravado como o WhatsApp o resolve (`resolve_br_number`) — em boa parte dos DDDs,
a forma CURTA. O usuário digita a que ele conhece, com o 9. Sem tolerância, o dono da conta
não é encontrado no `check`, o `register` estoura `PHONE_EXISTS` e o app só sabe dizer
"problema no nosso servidor": em 2026-07-28 isso trancou uma matrícula JÁ PAGA do lado de fora.
"""

import pytest

from users.profiles import interface as profiles

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_com_telefone_curto():
    """Perfil gravado SEM o 9 (como o WhatsApp resolveu) — o caso que quebrava."""
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="554299384069")
    return user


def test_acha_quem_digitou_com_o_nono_digito(user_com_telefone_curto):
    achado = profiles.find_by_phone("5542999384069")
    assert achado is not None, (
        "quem pagou digitou o próprio número e não foi encontrado"
    )
    assert achado.user_id == user_com_telefone_curto.pk


def test_acha_pela_forma_exata(user_com_telefone_curto):
    achado = profiles.find_by_phone("554299384069")
    assert achado is not None
    assert achado.user_id == user_com_telefone_curto.pk


def test_exists_phone_enxerga_as_duas_formas(user_com_telefone_curto):
    assert profiles.exists_phone("5542999384069")
    assert profiles.exists_phone("554299384069")


def test_nao_confunde_numeros_diferentes(user_com_telefone_curto):
    assert profiles.find_by_phone("5542988887777") is None


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # celular: as duas formas, sempre com a digitada primeiro
        ("5542999384069", ["5542999384069", "554299384069"]),
        ("554299384069", ["554299384069", "5542999384069"]),
        # fixo (8 dígitos começando com 3) não tem dualidade de 9º dígito
        ("554133334444", ["554133334444"]),
        # fora do formato BR canônico: devolve só o que veio, sem inventar
        ("4299938406", ["4299938406"]),
    ],
)
def test_variantes(entrada, esperado):
    assert profiles.phone_variants(entrada) == esperado
