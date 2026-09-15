"""G11 — race no re-upload de selfie: a task de validação usava `selfie_status != PENDING` pra
detectar re-upload, mas o novo upload TAMBÉM re-arma PENDING, então o veredito da foto A gravava
sobre a foto B (podia liberar B nunca validada). O discriminador real é `selfie_taken_at`, que muda
a cada upload.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.django_db


def _run(monkeypatch, tmp_path, *, reupload: bool):
    from users.roles import _selfie
    from users.roles.enrollment import service as es

    (tmp_path / "a.jpg").write_bytes(b"fake-selfie")
    monkeypatch.setattr(es.settings, "MEDIA_ROOT", str(tmp_path))

    saved = []

    class _Enr:
        id = 1
        selfie_image = "a.jpg"
        status = es._S.SELFIE
        selfie_status = _selfie.SelfieStatus.PENDING
        selfie_taken_at = "T1"
        selfie_reject_count = 0
        selfie_verified = False
        selfie_description = None
        external_id = "e1"
        user = type("U", (), {"external_id": "u1"})()
        hub = None

        def refresh_from_db(self, fields=None):
            # simula o que aconteceu no DB enquanto a task rodava liveness+face-match
            if reupload:
                self.selfie_taken_at = "T2"  # outro upload trocou a foto

        def save(self, **kw):
            saved.append(kw.get("update_fields"))

    mgr = MagicMock()
    mgr.select_related.return_value.filter.return_value.first.return_value = _Enr()
    monkeypatch.setattr(es.Enrollment, "objects", mgr)
    monkeypatch.setattr(_selfie, "verify", lambda *a, **k: (_selfie.APPROVED, "ok"))
    monkeypatch.setattr(_selfie, "add_face_match", lambda **k: (_selfie.APPROVED, "ok"))
    # evita efeitos colaterais (auditoria/notify) — só o guard está sob teste
    monkeypatch.setattr(es, "_save_selfie_audit", lambda *a, **k: None)
    monkeypatch.setattr(es, "_resolve_selfie", lambda enr: None)

    es.run_selfie_validation(1)
    return saved


def test_g11_reupload_descarta_veredito_da_foto_velha(monkeypatch, tmp_path):
    """taken_at mudou no meio tempo (re-upload) → o veredito da foto A NÃO é gravado."""
    saved = _run(monkeypatch, tmp_path, reupload=True)
    assert saved == [], "veredito da foto velha gravou sobre a nova (race G11)"


def test_g11_sem_reupload_grava_normal(monkeypatch, tmp_path):
    """Não-regressão: sem re-upload, o veredito é gravado normalmente."""
    saved = _run(monkeypatch, tmp_path, reupload=False)
    assert saved and "selfie_status" in saved[0]
