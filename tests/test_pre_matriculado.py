"""F4 — pré-matriculado → bolsista (Victor 2026-07-08).

O que trava: o gatilho `maybe_auto_enroll_bolsista` NÃO pode converter duas vezes (dois pagamentos
concorrentes do mesmo promotor) nem antes de bater 3 leads pagos. O guard é o `.update()`
condicional (baixa a flag atomicamente). Testado chamando o gatilho em sequência (simula a corrida).
"""

from __future__ import annotations

import uuid

import pytest


def _mk_promoter(*, pre_matriculado: bool):
    """User + Profile + Hub + Promoter mínimos. Devolve (user, hub, promoter)."""
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.profiles.models import Profile
    from users.roles.promoter.models import Promoter

    coord = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(city="São Paulo", state="SP")
    hub = Hub.objects.create(
        address=addr, brand="test", coordinator=coord, is_default=True
    )
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(
        user=user, cpf=str(uuid.uuid4().int)[:11], phone=str(uuid.uuid4().int)[:13]
    )
    promoter = Promoter.objects.create(
        user=user, hub=hub, pre_matriculado=pre_matriculado
    )
    return user, hub, promoter


def _add_paid_leads(promoter_user, hub, n: int):
    """Cria N leads PAGOS (self_study=False) captados pelo promotor."""
    from users.auth.models import User
    from users.roles.lead.models import Lead

    for _ in range(n):
        lead_user = User.objects.create_user(external_id=uuid.uuid4())
        Lead.objects.create(
            user=lead_user,
            promoter=promoter_user,
            status=Lead.Status.PAID,
            self_study=False,
        )


@pytest.mark.django_db
def test_auto_enroll_converte_uma_vez_e_baixa_flag():
    from users.roles.enrollment.models import Enrollment
    from users.roles.promoter import service as promoter_iface
    from users.roles.promoter.models import Promoter

    user, hub, _ = _mk_promoter(pre_matriculado=True)
    _add_paid_leads(user, hub, 3)

    # duas chamadas em sequência simulam dois pagamentos concorrentes: só a 1ª converte.
    first = promoter_iface.maybe_auto_enroll_bolsista(user)
    second = promoter_iface.maybe_auto_enroll_bolsista(user)

    assert first is True and second is False
    assert Enrollment.objects.filter(user=user).count() == 1
    enr = Enrollment.objects.get(user=user)
    assert enr.bolsista is True
    assert Promoter.objects.get(user=user).pre_matriculado is False


@pytest.mark.django_db
def test_auto_enroll_espera_os_3_e_restaura_flag():
    from users.roles.enrollment.models import Enrollment
    from users.roles.promoter import service as promoter_iface
    from users.roles.promoter.models import Promoter

    user, hub, _ = _mk_promoter(pre_matriculado=True)
    _add_paid_leads(user, hub, 2)  # só 2 → ainda não converte

    converted = promoter_iface.maybe_auto_enroll_bolsista(user)

    assert converted is False
    assert Enrollment.objects.filter(user=user).count() == 0
    # a flag foi restaurada (o guard baixou e desfez) → o próximo lead pago reavalia
    assert Promoter.objects.get(user=user).pre_matriculado is True


@pytest.mark.django_db
def test_auto_enroll_ignora_quem_nao_e_pre_matriculado():
    from users.roles.enrollment.models import Enrollment
    from users.roles.promoter import service as promoter_iface

    user, hub, _ = _mk_promoter(pre_matriculado=False)
    _add_paid_leads(user, hub, 5)

    assert promoter_iface.maybe_auto_enroll_bolsista(user) is False
    assert Enrollment.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_bolsista_so_libera_prova_com_10_indicacoes_pagas(monkeypatch):
    from users.roles.student import service as student_iface
    from users.roles.student.models import Student

    user, hub, _ = _mk_promoter(pre_matriculado=False)
    student = Student.objects.create(
        user=user,
        hub=hub,
        self_study=True,
        bolsista=True,
        status=Student.Status.DOCUMENTS_UNDER_REVIEW,
        blood_type="O+",
    )
    monkeypatch.setattr(
        student_iface, "_required_doc_types_for", lambda _student: set()
    )
    monkeypatch.setattr(student_iface, "_notify", lambda *args, **kwargs: None)

    _add_paid_leads(user, hub, 9)
    student_iface._maybe_release_exam(student)
    student.refresh_from_db()
    assert student.status == Student.Status.DOCUMENTS_UNDER_REVIEW

    _add_paid_leads(user, hub, 1)
    student_iface._maybe_release_exam(student)
    student.refresh_from_db()
    assert student.status == Student.Status.EXAM_RELEASED
