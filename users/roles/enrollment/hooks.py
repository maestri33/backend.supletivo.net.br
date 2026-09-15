"""Hooks do ciclo da TAXA da matrícula (plan/14; CONVENTION §7.3).

O worker do `finance` reconcilia a fila com o Asaas e dispara `fee.paid`/`fee.problem`; aqui a
matrícula reage: 1ª parcela PAGA → status `fee_paid` + notify ao coordenador (gatilho do mundo
real: a instituição só libera as credenciais com a 1ª paga); qualquer B.O. → notify ao
coordenador. O ALUNO nunca é notificado (política interna do polo — Victor 2026-06-12).
Registrado em `core.hooks` no boot (`users` AppConfig.ready), igual ao `payment.paid` do lead.
"""

from __future__ import annotations


def on_fee_paid(
    *,
    external_reference: str,
    source_type: str,
    source_external_id: str,
    amount=None,
    **_,
) -> bool:
    """True se a fee era de uma matrícula (consumido); False senão (outro app pode consumir)."""
    from users.roles.enrollment import service

    if source_type != "enrollment":
        return False
    enr = service.get_by_external_id(source_external_id)
    if enr is None:
        return False
    return service.apply_fee_paid(
        enr, external_reference=external_reference, amount=amount
    )


def on_fee_problem(
    *,
    external_reference: str,
    source_type: str,
    source_external_id: str,
    detail=None,
    asaas_status=None,
    **_,
) -> bool:
    """B.O. com uma parcela da taxa → notifica o coordenador do polo da matrícula."""
    from users.roles.enrollment import service

    if source_type != "enrollment":
        return False
    enr = service.get_by_external_id(source_external_id)
    if enr is None:
        return False
    return service.apply_fee_problem(
        enr,
        external_reference=external_reference,
        detail=detail,
        asaas_status=asaas_status,
    )
