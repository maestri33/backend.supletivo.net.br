"""F2 — flag de encontro presencial da selfie (Victor 2026-07-08).

O que trava: a flag `selfie_needs_meeting` mora no Profile (nível-pessoa) DE PROPÓSITO — ela sobe no
cadastro (candidato/aluno reprovou a selfie 5×) e precisa sobreviver às trocas de role até o fim do
curso, onde o `student._maybe_release_exam` a lê pra exigir o encontro. Testa a persistência + o helper.
"""

from __future__ import annotations

import uuid

import pytest


def _mk_user():
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(
        user=user, cpf=str(uuid.uuid4().int)[:11], phone=str(uuid.uuid4().int)[:13]
    )
    return user


@pytest.mark.django_db
def test_flag_sobe_e_persiste_no_profile():
    from users.profiles import interface as profiles

    user = _mk_user()
    assert profiles.get(user).selfie_needs_meeting is False

    profiles.set_selfie_needs_meeting(user)
    # relê do banco (não do objeto em memória) — a flag tem que estar persistida
    assert (
        profiles.find_by_external_id(str(user.external_id)).selfie_needs_meeting is True
    )

    # e o coordenador limpa (fim do curso, foto manual)
    profiles.set_selfie_needs_meeting(user, False)
    assert (
        profiles.find_by_external_id(str(user.external_id)).selfie_needs_meeting
        is False
    )


@pytest.mark.django_db
def test_flag_sobe_na_5a_reprovacao_nao_antes():
    """O gate do `_resolve_selfie` é `reject_count >= MAX`. Confere o limiar (5) no helper de contagem."""
    from users.roles import _selfie

    assert _selfie.MAX_REJECTS_BEFORE_MEETING == 5
    # append_reason acumula um bloco por tentativa (não sobrescreve)
    desc = None
    for i in range(1, 4):
        desc = _selfie.append_reason(desc, i, f"motivo {i}")
    assert "tentativa 1" in desc and "tentativa 3" in desc
    assert desc.count("[tentativa") == 3
