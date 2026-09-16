import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from django.conf import settings
from integrations.tools.biometric import face_match, service
from integrations.tools.biometric.exceptions import NoFaceDetected, ModelUnavailable
from integrations.tools.biometric.models import FaceBiometric, FaceVerification
from users.models import User


@pytest.fixture
def dummy_image(tmp_path):
    img_file = tmp_path / "test_face.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00")
    return str(img_file)


def test_embed_remote_service_success(settings, dummy_image):
    settings.BIOMETRIC_SERVICE_URL = "http://biometric-svc:8001"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    fake_embedding = [0.1] * 512
    mock_response.json.return_value = {
        "embedding": fake_embedding,
        "det_score": 0.99,
        "meta": {"det_score": 0.99, "bbox": [10, 10, 100, 100], "faces": 1},
    }

    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        emb, meta = face_match.embed(dummy_image)
        assert len(emb) == 512
        assert meta["det_score"] == 0.99
        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        assert call_url == "http://biometric-svc:8001/embed"


def test_embed_remote_service_no_face_detected(settings, dummy_image):
    settings.BIOMETRIC_SERVICE_URL = "http://biometric-svc:8001"
    
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.json.return_value = {"detail": "nenhum rosto detectado"}

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(NoFaceDetected, match="nenhum rosto detectado"):
            face_match.embed(dummy_image)


def test_embed_remote_service_server_error(settings, dummy_image):
    settings.BIOMETRIC_SERVICE_URL = "http://biometric-svc:8001"
    
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelUnavailable, match="serviço biométrico HTTP 500"):
            face_match.embed(dummy_image)


@pytest.mark.django_db
def test_verify_identity_uses_only_current_probe(settings, dummy_image):
    settings.BIOMETRIC_SERVICE_URL = "http://biometric-svc:8001"
    
    user = User.objects.create(is_active=True)
    
    # 1. Cria um documento de referência (RG) com embedding [1.0, 0, 0, ...]
    doc_emb = [0.0] * 512
    doc_emb[0] = 1.0
    FaceBiometric.objects.create(
        user=user,
        source=FaceBiometric.Source.DOCUMENT,
        image_path="docs/rg.jpg",
        embedding=doc_emb,
        det_score=0.98,
    )
    
    # 2. Cria uma selfie antiga (sem ser âncora aprovada) que por acaso tinha score alto com o RG
    old_selfie_emb = [0.0] * 512
    old_selfie_emb[0] = 0.99  # Quase idêntica ao RG
    old_selfie = FaceBiometric.objects.create(
        user=user,
        source=FaceBiometric.Source.SELFIE,
        image_path="selfies/old.jpg",
        embedding=old_selfie_emb,
        det_score=0.95,
    )
    
    # 3. Agora o usuário envia uma nova selfie com embedding completamente diferente [0, 1.0, 0, ...]
    new_selfie_emb = [0.0] * 512
    new_selfie_emb[1] = 1.0  # Ortogonal ao RG (cosseno 0)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "embedding": new_selfie_emb,
        "det_score": 0.95,
        "meta": {"det_score": 0.95, "bbox": [5, 5, 50, 50], "faces": 1},
    }
    
    with patch("httpx.Client.post", return_value=mock_response):
        res = service.verify_identity(
            user=user,
            selfie_image_path=dummy_image,
            caller="test_probe_isolation",
        )
    
    # A selfie atual é ortogonal ao RG (score ~ 0), portanto deve ser REJEITADA
    # No código com delírio antigo, ela pegava a old_selfie da galeria e era aprovada com score 0.99!
    assert res.score is not None
    assert res.score < settings.BIOMETRIC_REVIEW_THRESHOLD
    assert res.match is False
    assert res.status == "rejected"
    
    verification = FaceVerification.objects.filter(user=user).order_by("-created_at").first()
    assert verification is not None
    assert verification.approved is False
    assert verification.probe.embedding == new_selfie_emb
    assert verification.probe.id != old_selfie.id
