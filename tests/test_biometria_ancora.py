"""Selfie aprovada vira ÂNCORA de identidade (Victor 2026-07-29).

Duas coisas: (1) a selfie que passou entra como referência das próximas — o documento envelhece,
a selfie conferida é a cara atual; (2) com âncora, a galeria de tentativas antigas NÃO entra mais
como probe — antes o "melhor par" aprovava a foto nova usando a nota de uma antiga, ou seja, a
pessoa da vez não precisava bater com ninguém.
"""

import pytest

from integrations.tools.biometric import service as bio
from integrations.tools.biometric.models import FaceBiometric, FaceVerification

pytestmark = pytest.mark.django_db


def _user():
    from users.auth.models import User
    from users.profiles.models import Profile

    u = User.objects.create(is_active=True)
    Profile.objects.create(user=u, phone="5543999990077")
    return u


def _bio(user, source, emb):
    return FaceBiometric.objects.create(
        user=user, source=source, image_path="x.jpg", embedding=emb, provider="test"
    )


def test_selfie_aprovada_vira_ancora():
    u = _user()
    selfie = _bio(u, FaceBiometric.Source.SELFIE, [1.0, 0.0])
    FaceVerification.objects.create(
        user=u,
        caller="t",
        probe=selfie,
        score=0.9,
        threshold=0.5,
        approved=True,
        status="approved",
    )
    assert [b.id for b in bio._selfies_aprovadas(u)] == [selfie.id]


def test_selfie_reprovada_nao_vira_ancora():
    """Senão o impostor da primeira tentativa vira o gabarito das próximas."""
    u = _user()
    ruim = _bio(u, FaceBiometric.Source.SELFIE, [0.0, 1.0])
    FaceVerification.objects.create(
        user=u,
        caller="t",
        probe=ruim,
        score=0.1,
        threshold=0.5,
        approved=False,
        status="rejected",
    )
    assert bio._selfies_aprovadas(u) == []


def test_ancora_exclui_a_propria_foto_da_vez():
    """A selfie sendo avaliada não pode ser referência de si mesma (cosseno 1.0 sempre)."""
    u = _user()
    s1 = _bio(u, FaceBiometric.Source.SELFIE, [1.0, 0.0])
    FaceVerification.objects.create(
        user=u,
        caller="t",
        probe=s1,
        score=0.9,
        threshold=0.5,
        approved=True,
        status="approved",
    )
    assert bio._selfies_aprovadas(u, exclude_id=s1.id) == []
