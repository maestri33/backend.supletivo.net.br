"""Gate de /media/ privado. Duas camadas:

G1 (não-autenticado): o classificador olhava só o 1º segmento do path, então
`training/../documents/<tok>.jpg` era classificado como público (`training`) e servido SEM token —
apesar de o arquivo final ser privado (`documents`). Normalização de path fecha isso → 401.

GATE DE DONO (IDOR, 2026-07-10): antes qualquer usuário AUTENTICADO baixava o arquivo de qualquer
outro (só precisava de um JWT válido + saber o token). Agora `media_serve` amarra o dono pelo path
(`core.media.owner_external_id_for_path`) e só serve pro DONO ou pra REVISOR (coordenador/superuser).
"""

import os
import tempfile
import uuid

import pytest
from django.conf import settings
from django.test import RequestFactory

from core.media_views import media_serve
from users.auth.jwt import service as jwt


@pytest.fixture
def media_root(monkeypatch):
    root = tempfile.mkdtemp()
    monkeypatch.setattr(settings, "MEDIA_ROOT", root)
    os.makedirs(f"{root}/documents")
    os.makedirs(f"{root}/training")
    with open(f"{root}/documents/rg_secreto.jpg", "wb") as fh:
        fh.write(b"RG PRIVADO DE TERCEIRO")
    with open(f"{root}/training/publico.jpg", "wb") as fh:
        fh.write(b"material publico")
    return root


def _status(path):
    return media_serve(RequestFactory().get(f"/media/{path}"), path).status_code


def test_privado_direto_sem_token_401(media_root):
    assert _status("documents/rg_secreto.jpg") == 401


def test_traversal_para_privado_sem_token_bloqueado(media_root):
    """O CORE do G1: mudar de prefixo com `../` não pode escapar do gate."""
    assert _status("training/../documents/rg_secreto.jpg") == 401


def test_publico_serve_sem_token(media_root):
    assert _status("training/publico.jpg") == 200


def test_traversal_para_fora_do_root_nao_vaza(media_root):
    """`../../etc/passwd` normaliza pra dentro do root e não acha nada → Http404 (=404 no stack),
    nunca serve /etc/passwd nem estoura SuspiciousFileOperation (500)."""
    from django.http import Http404

    with pytest.raises(Http404):
        _status("../../../../etc/passwd")


# ── Gate de DONO (IDOR) ───────────────────────────────────────────────────────

_RG_PATH = "documents/rg_secreto.jpg"  # o arquivo que a fixture media_root grava


def _serve_as(path, token):
    req = RequestFactory().get(f"/media/{path}", HTTP_AUTHORIZATION=f"Bearer {token}")
    return media_serve(req, path)


def _mk_user(*, roles=(), is_superuser=False):
    from users.auth.models import User

    u = User.objects.create_user(external_id=uuid.uuid4(), is_active=True)
    if is_superuser:
        User.objects.filter(pk=u.pk).update(is_superuser=True)
    ext = str(u.external_id)
    return u, ext, jwt.issue(ext, list(roles))["access_token"]


def _own_rg(user):
    """Amarra `_RG_PATH` a `user` via RG.front_photo → Document.user (o que o resolver consulta)."""
    from users.documents.models import RG, Document

    doc = Document.objects.create(user=user)
    RG.objects.create(document=doc, front_photo=_RG_PATH)


@pytest.mark.django_db
def test_dono_baixa_o_proprio_rg_200(media_root):
    owner, _ext, token = _mk_user()
    _own_rg(owner)
    assert _serve_as(_RG_PATH, token).status_code == 200


@pytest.mark.django_db
def test_logado_nao_dono_recebe_403(media_root):
    """CORE do IDOR: outro usuário autenticado NÃO baixa o RG alheio, mesmo com JWT válido."""
    owner, _ext, _tok = _mk_user()
    _own_rg(owner)
    _outro, _ext2, intruso_token = _mk_user()
    assert _serve_as(_RG_PATH, intruso_token).status_code == 403


@pytest.mark.django_db
def test_coordenador_revisa_qualquer_rg_200(media_root):
    owner, _ext, _tok = _mk_user()
    _own_rg(owner)
    _coord, _ext2, coord_token = _mk_user(roles=["coordinator"])
    assert _serve_as(_RG_PATH, coord_token).status_code == 200


@pytest.mark.django_db
def test_superuser_revisa_qualquer_rg_200(media_root):
    owner, _ext, _tok = _mk_user()
    _own_rg(owner)
    _su, _ext2, su_token = _mk_user(is_superuser=True)
    assert _serve_as(_RG_PATH, su_token).status_code == 200


@pytest.mark.django_db
def test_privado_sem_dono_no_db_nega_nao_revisor_403(media_root):
    """Path privado que não resolve dono (órfão/receipt): não-revisor autenticado → 403 (fail-closed)."""
    _u, _ext, token = _mk_user()  # ninguém amarrou _RG_PATH
    assert _serve_as(_RG_PATH, token).status_code == 403


def _write_audit_selfie(media_root):
    """Recorte de rosto da auditoria da IA (audit/selfie/<tok>/rosto_documento.jpg)."""
    os.makedirs(f"{media_root}/audit/selfie/tok123")
    path = "audit/selfie/tok123/rosto_documento.jpg"
    with open(f"{media_root}/{path}", "wb") as fh:
        fh.write(b"RECORTE DE ROSTO DO RG")
    return path


def test_audit_selfie_sem_token_401(media_root):
    """`audit/` virou privado: recorte de rosto não é mais servido sem auth."""
    assert _status(_write_audit_selfie(media_root)) == 401


@pytest.mark.django_db
def test_audit_selfie_nao_revisor_403(media_root):
    path = _write_audit_selfie(media_root)
    _u, _ext, token = _mk_user()  # sem dono resolvível → só revisor
    assert _serve_as(path, token).status_code == 403


@pytest.mark.django_db
def test_audit_selfie_coordenador_200(media_root):
    path = _write_audit_selfie(media_root)
    _c, _ext, coord_token = _mk_user(roles=["coordinator"])
    assert _serve_as(path, coord_token).status_code == 200
