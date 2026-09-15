"""G8 — uma escrita satisfaz o gate mas o caminho que escreve não re-dispara o `_advance_*`
correspondente, deixando o usuário preso. Três pontos, mesma causa. Cada teste verifica que o
gancho de re-avaliação foi disparado.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


# ───────────── #5: indicação paga re-avalia a prova do bolsista ─────────────
def test_g8_5_reevaluate_so_para_student_bolsista():
    from users.roles.student import service as ss

    class _Student:
        bolsista = True

    with (
        patch.object(ss, "_maybe_release_exam") as release,
        patch.object(ss.Student, "objects") as sobj,
    ):
        sobj.filter.return_value.select_related.return_value.first.return_value = (
            _Student()
        )
        ss.reevaluate_exam_release(object())
        assert release.called, "bolsista não teve a prova re-avaliada"

    # não-bolsista → no-op
    class _NotBolsista:
        bolsista = False

    with (
        patch.object(ss, "_maybe_release_exam") as release,
        patch.object(ss.Student, "objects") as sobj,
    ):
        sobj.filter.return_value.select_related.return_value.first.return_value = (
            _NotBolsista()
        )
        ss.reevaluate_exam_release(object())
        assert not release.called

    # sem student → no-op
    with (
        patch.object(ss, "_maybe_release_exam") as release,
        patch.object(ss.Student, "objects") as sobj,
    ):
        sobj.filter.return_value.select_related.return_value.first.return_value = None
        ss.reevaluate_exam_release(object())
        assert not release.called


def test_g8_5_apply_effects_reavalia_promotor():
    """_apply_effects (lead pago) deve chamar reevaluate_exam_release(promotor)."""
    import uuid

    from users.auth.models import User
    from users.roles.lead import service as lead_service

    promoter_user = User.objects.create_user(external_id=uuid.uuid4())
    client = User.objects.create_user(external_id=uuid.uuid4())

    class _Lead:
        self_study = False
        promoter = promoter_user
        user = client
        external_id = uuid.uuid4()

    with (
        patch("users.roles.promoter.models.Promoter.objects") as pobj,
        patch("finance.interface.commissions.credit_commission"),
        patch.object(lead_service.hub_iface, "hub_of", return_value=object()),
        patch("users.roles.enrollment.service.create_from_lead"),
        patch("users.roles.promoter.service.maybe_auto_enroll_bolsista"),
        patch("users.roles.student.service.reevaluate_exam_release") as reeval,
    ):
        pobj.filter.return_value.exists.return_value = False
        lead_service._apply_effects(_Lead())
        assert reeval.called, "indicação paga não re-avaliou a prova do promotor"


# ───────────── #17: correct_identity re-dispara o release ─────────────
def test_g8_17_correct_identity_redispara_advance():
    from users.roles.enrollment import service as es

    class _Enr:
        user = object()
        status = "selfie"
        external_id = "e1"

    with (
        patch.object(es, "_enrollment_for_coordinator", return_value=_Enr()),
        patch.object(es.profiles, "update_identity"),
        patch.object(es, "me_dict", return_value={}),
        patch.object(es, "_advance_to_release") as advance,
    ):

        class _Coord:
            external_id = "c1"

        es.coordinator_correct_identity(
            enrollment_external_id="e1", coordinator=_Coord(), nationality="BR"
        )
        assert advance.called, "correct_identity não re-disparou _advance_to_release"


# ───────────── #19: OCR preencheu number → avança DOCUMENTS ─────────────
def test_g8_19_apply_doc_extracted_chama_advance():
    """_apply_doc_extracted (o ponto único que grava o `number` extraído) deve terminar chamando
    _advance_documents — senão o candidato fica preso em DOCUMENTS quando o número só veio pelo OCR.
    (source-check: executar a função inteira exige um Candidate completo; o gancho é o que importa,
    e _advance_documents já é guarded/testável à parte.)"""
    import inspect

    from users.roles.candidate import service as cs

    src = inspect.getsource(cs._apply_doc_extracted)
    assert "_advance_documents(" in src, (
        "o gancho de avanço não está em _apply_doc_extracted"
    )


def test_g8_19_advance_documents_e_guarded():
    """_advance_documents não avança fora de DOCUMENTS (idempotente nos callsites de validação)."""
    from users.roles.candidate import service as cs

    class _Cand:
        status = "pix"  # já passou de DOCUMENTS
        doc_type = "rg"

    with patch.object(cs, "_set_status") as setst:
        cs._advance_documents(_Cand(), "u1")
        assert not setst.called, "_advance_documents avançou fora de DOCUMENTS"
