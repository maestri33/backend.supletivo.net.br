"""G2 da auditoria: sessão não-revogável.

`is_active=False` é o único mecanismo de ban, mas `JWTAuth.authenticate` (e o `refresh`) nunca
liam `is_active` — só `version_matches`, que comparava a versão dos claims com a do DB, e a versão
só sobe em troca de role. Resultado: banir um usuário não derrubava o access dele nem impedia o
refresh de renovar por mais 24h.

Fix: `current_version` retorna um sentinel negativo pra usuário inexistente/inativo — que nunca
bate com uma versão real de claims (>=0), derrubando access E refresh de uma vez.
"""

import pytest

from users.auth.jwt import service as jwt

pytestmark = pytest.mark.django_db


def _user(active=True):
    import uuid

    from users.auth.models import User

    return User.objects.create_user(external_id=uuid.uuid4(), is_active=active)


def test_token_valido_enquanto_ativo():
    u = _user()
    ext = str(u.external_id)
    assert jwt.version_matches(ext, jwt.current_version(ext)) is True


def test_desativar_derruba_access():
    from users.auth.models import User

    u = _user()
    ext = str(u.external_id)
    claims_version = jwt.current_version(
        ext
    )  # versão que um token emitido agora carregaria
    User.objects.filter(pk=u.pk).update(is_active=False)
    assert jwt.version_matches(ext, claims_version) is False


def test_desativar_barra_refresh():
    from users.auth.models import User

    u = _user()
    ext = str(u.external_id)
    par = jwt.issue(ext, ["student"])
    User.objects.filter(pk=u.pk).update(is_active=False)
    with pytest.raises(jwt.TokenError):
        jwt.refresh(par["refresh_token"])


def test_usuario_inexistente_nao_valida():
    assert jwt.version_matches("00000000-0000-0000-0000-000000000000", 0) is False


def test_reativar_restaura_a_versao():
    """Ban é reversível: reativar volta a bater (revogar sessão comprometida é bump de versão, não ban)."""
    from users.auth.models import User

    u = _user()
    ext = str(u.external_id)
    v = jwt.current_version(ext)
    User.objects.filter(pk=u.pk).update(is_active=False)
    User.objects.filter(pk=u.pk).update(is_active=True)
    assert jwt.version_matches(ext, v) is True
