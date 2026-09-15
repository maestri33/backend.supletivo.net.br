"""G21 — o pipeline de selfie do candidate é cópia do enrollment que divergiu. Aqui os 2 pontos de
corretude/segurança: (#13) mime da selfie hardcoded como image/jpeg, e o mesmo race do G11 (guard
por status, que não detecta re-upload). Os pontos de paridade (auditoria por-tentativa, reconcile
de análise stale) ficam para o refactor que extrai o pipeline compartilhado — não são bug ativo.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.django_db


def _run(monkeypatch, tmp_path, *, reupload: bool, ext: str = "jpg"):
    from users.roles import _selfie
    from users.roles.candidate import service as cs

    (tmp_path / f"s.{ext}").write_bytes(b"fake-selfie")
    monkeypatch.setattr(cs.settings, "MEDIA_ROOT", str(tmp_path))

    seen = {"content_type": None, "saved": []}

    class _Cand:
        id = 1
        selfie_image = f"s.{ext}"
        status = cs._S.SELFIE
        selfie_status = _selfie.SelfieStatus.PENDING
        selfie_taken_at = "T1"
        selfie_reject_count = 0
        selfie_verified = False
        selfie_description = None
        external_id = "c1"
        user = type("U", (), {"external_id": "u1"})()
        hub = None

        def refresh_from_db(self, fields=None):
            if reupload:
                self.selfie_taken_at = "T2"

        def save(self, **kw):
            seen["saved"].append(kw.get("update_fields"))

    mgr = MagicMock()
    mgr.select_related.return_value.filter.return_value.first.return_value = _Cand()
    monkeypatch.setattr(cs.Candidate, "objects", mgr)

    def fake_verify(image_bytes, content_type, **k):
        seen["content_type"] = content_type
        return _selfie.APPROVED, "ok"

    monkeypatch.setattr(_selfie, "verify", fake_verify)
    monkeypatch.setattr(_selfie, "add_face_match", lambda **k: (_selfie.APPROVED, "ok"))
    monkeypatch.setattr(cs, "_resolve_selfie", lambda cand: None)

    cs.run_selfie_validation(1)
    return seen


def test_g21_13_mime_derivado_da_extensao(monkeypatch, tmp_path):
    """Selfie .png → content_type image/png (não o image/jpeg hardcoded)."""
    seen = _run(monkeypatch, tmp_path, reupload=False, ext="png")
    assert seen["content_type"] == "image/png"


def test_g21_g11_reupload_descarta_veredito_velho(monkeypatch, tmp_path):
    """Mesmo race do G11: re-upload (taken_at mudou) → veredito da foto velha não é gravado."""
    seen = _run(monkeypatch, tmp_path, reupload=True)
    assert seen["saved"] == [], (
        "veredito da foto velha gravou sobre a nova (race no candidate)"
    )


def test_g21_g11_sem_reupload_grava(monkeypatch, tmp_path):
    seen = _run(monkeypatch, tmp_path, reupload=False)
    assert seen["saved"] and "selfie_status" in seen["saved"][0]
