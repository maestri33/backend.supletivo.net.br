"""Re-upload não deixa PII órfã."""

import tempfile

import pytest

pytestmark = pytest.mark.django_db


# ───────────────────────── G13: re-upload não deixa órfã ─────────────────────────
def test_g13_replace_media_deleta_antigo(monkeypatch):
    from django.conf import settings
    from django.core.files.storage import default_storage

    from core.media import replace_media

    root = tempfile.mkdtemp()
    monkeypatch.setattr(settings, "MEDIA_ROOT", root)

    old = replace_media(old=None, prefix="selfie", data=b"foto A", ext="jpg")
    assert default_storage.exists(old)

    new = replace_media(old=old, prefix="selfie", data=b"foto B", ext="jpg")
    assert default_storage.exists(new)
    assert not default_storage.exists(old), "selfie antiga ficou órfã no storage"
    assert new != old


def test_g13_primeiro_upload_sem_antigo():
    """old=None (1º upload) não quebra."""
    import tempfile as _t

    from django.conf import settings
    from django.core.files.storage import default_storage

    from core.media import replace_media

    settings.MEDIA_ROOT = _t.mkdtemp()
    p = replace_media(old=None, prefix="selfie", data=b"x", ext="jpg")
    assert default_storage.exists(p)
