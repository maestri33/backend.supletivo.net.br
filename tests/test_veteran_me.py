"""`/veteran/me` — a composição student × enrollment que saiu do `student.service` pra rota.

O bloco `enrollment` era montado dentro de `student.service.veteran_detail`; isso fazia
`student.service` importar `enrollment.service`, que já importa `student.service` no `conclude`
(ciclo — ver `test_import_cycles`). A composição virou responsabilidade da rota. Estes testes
travam o CONTRATO que o front consome: as 5 chaves, e `None` quando não há matrícula.
"""

import pytest

import api.clients as clients


@pytest.fixture
def veteran_route(monkeypatch):
    """Chama `veteran_me` sem HTTP/DB: só o gate de role e os dois services são falsos."""
    monkeypatch.setattr(clients, "_veteran_guard", lambda request: "ext-123")
    monkeypatch.setattr(
        clients.student_iface,
        "veteran_detail",
        lambda *, user_external_id: {"user": {"external_id": user_external_id}},
    )

    def run(*, enrollment, me_dict=None):
        monkeypatch.setattr(
            clients.enrollment_iface,
            "get_for_user_external_id",
            lambda ext: enrollment,
        )
        monkeypatch.setattr(
            clients.enrollment_iface, "me_dict", lambda enr: me_dict or {}
        )
        return clients.veteran_me(request=None)

    return run


def test_bloco_enrollment_traz_exatamente_as_5_chaves(veteran_route):
    """O front recebe profile/address/education/rg/selfie — e nada mais do me_dict rico."""
    data = veteran_route(
        enrollment=object(),
        me_dict={
            "profile": {"name": "Ana"},
            "address": {"zipcode": "01001000"},
            "education": {"grade": "EM"},
            "rg": {"validation_status": "approved"},
            "selfie": {"status": "approved"},
            # ruído que o me_dict carrega e o veterano NÃO deve receber:
            "fee": {"status": "paid"},
            "status_wizard": "concluded",
        },
    )
    assert set(data["enrollment"]) == {
        "profile",
        "address",
        "education",
        "rg",
        "selfie",
    }
    assert data["enrollment"]["profile"] == {"name": "Ana"}
    assert data["user"]["external_id"] == "ext-123"  # o bloco student segue intacto


def test_sem_matricula_o_bloco_e_none(veteran_route):
    """Veterano sem Enrollment persistido → `enrollment: null` (não estoura, não some a chave)."""
    data = veteran_route(enrollment=None)
    assert data["enrollment"] is None
    assert "user" in data


def test_chave_ausente_no_me_dict_vira_none(veteran_route):
    """me_dict incompleto → a chave existe com None (o front nunca recebe KeyError)."""
    data = veteran_route(enrollment=object(), me_dict={"profile": {"name": "Bia"}})
    assert data["enrollment"]["profile"] == {"name": "Bia"}
    assert data["enrollment"]["rg"] is None


def test_student_service_nao_monta_mais_o_bloco():
    """Guarda contra reintroduzir a aresta: o service do student não devolve `enrollment`."""
    import inspect

    from users.roles.student import service as student_service

    src = inspect.getsource(student_service.veteran_detail)
    assert "enrollment_iface" not in src
    assert '"enrollment"' not in src
