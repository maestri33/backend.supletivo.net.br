import io

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from users.exceptions import ValidationError

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("photos", "expected"),
    [
        ({}, "rg_front"),
        ({"rg_front": {"status": "approved"}}, "rg_back"),
        ({"rg_full": {"status": "rejected"}}, "rg_full"),
        ({"rg_front": {"status": "pending"}}, None),
        ({"rg_front": {"status": "approved"}, "rg_back": {"status": "approved"}}, None),
    ],
)
def test_proximo_slot_do_documento(photos, expected):
    from users.roles._analysis import next_document_slot

    assert next_document_slot("rg", photos) == expected


def _png(color: str) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "PNG")
    return SimpleUploadedFile(
        "document.png", buffer.getvalue(), content_type="image/png"
    )


def _user_with_documents():
    from users.auth.models import User
    from users.documents import service as documents

    user = User.objects.create_user()
    documents.create_empty(user)
    return user


def _temporary_storage(monkeypatch, tmp_path):
    from core import media
    from users.documents import service as documents

    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(documents, "default_storage", storage)
    monkeypatch.setattr(media, "default_storage", storage)
    return documents


def test_rejeita_mesma_foto_como_frente_e_verso(monkeypatch, tmp_path):
    user = _user_with_documents()
    documents = _temporary_storage(monkeypatch, tmp_path)

    documents.upload_photo(str(user.external_id), "rg_front", _png("white"))

    with pytest.raises(ValidationError) as caught:
        documents.upload_photo(str(user.external_id), "rg_back", _png("white"))

    assert caught.value.code == "DOCUMENT_SIDE_DUPLICATE"
    assert "igual à frente" in caught.value.detail
    rg = documents.get_rg(str(user.external_id))
    assert rg.front_photo
    assert not rg.back_photo


def test_aceita_fotos_diferentes_para_frente_e_verso(monkeypatch, tmp_path):
    user = _user_with_documents()
    documents = _temporary_storage(monkeypatch, tmp_path)

    documents.upload_photo(str(user.external_id), "rg_front", _png("white"))
    documents.upload_photo(str(user.external_id), "rg_back", _png("black"))

    rg = documents.get_rg(str(user.external_id))
    assert rg.front_photo
    assert rg.back_photo
    assert rg.front_photo != rg.back_photo
