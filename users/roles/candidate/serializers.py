from __future__ import annotations

from users.address import interface as address_iface
from users.blocks import service as blocks
from users.documents import service as documents_iface
from users.exceptions import NotFound
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import _ADDRESS_FIELDS


def _selfie_dict(cand: Candidate) -> dict:
    from users.roles.candidate.selfie import _selfie_dict as sd
    return sd(cand)

def to_dict(cand: Candidate) -> dict:
    return {
        "external_id": str(cand.external_id),
        "status": cand.status,
        "hub_external_id": str(cand.hub.external_id),
        "pix_validated": cand.pix_validated,
        "selfie_verified": cand.selfie_verified,
        "selfie_status": cand.selfie_status,
    }



def me_dict(cand: Candidate) -> dict:
    """GET /me RICO do candidato (espelha `enrollment.me_dict`, plan/15): `status` + cada seção já
    preenchida + `missing_fields` por seção, numa chamada só. Bloco `None`/vazio = seção ainda não
    preenchida. **Toda mutação devolve este shape** → o front roteia o wizard sem re-fetch."""
    user_ext = str(cand.user.external_id)
    p = profiles.get(cand.user)

    # SEMPRE presente quando há Profile (fix Marilu 2026-07-05): name/birth_date vêm do CPFHub no
    # cadastro — o gate antigo (só montava se filiação preenchida) escondia birth_date do /me.
    profile = None
    if p:
        profile = {
            "mother_name": p.mother_name,
            "father_name": p.father_name,
            "birthplace": p.birthplace,
            "marital_status": p.marital_status,
            "nationality": p.nationality,
            "name": p.name,
            "birth_date": p.birth_date.isoformat() if p.birth_date else None,
            # escolaridade (nível-pessoa, F3): o front usa pra renderizar/pré-marcar a etapa `education`.
            "education_level": p.education_level,
            "education_completed": p.education_completed,
            "education_grade": p.education_grade,
            "education_last_completed_grade": p.education_last_completed_grade,
            "education_qualification": p.education_qualification,
            "education_last_completed_qualification": p.education_last_completed_qualification,
            "education_status": p.education_status,
            "education_year": p.education_year,
            "education_city": p.education_city,
            "education_school": p.education_school,
            # autoritativos do CPFHub — nenhum endpoint do candidato os edita; o front usa
            # esta flag pra travar/destacar os inputs (sombra verde + ✓).
            "locked_fields": ["name", "birth_date"],
        }

    # Candidato ainda SEM endereço é o estado normal no começo do funil — não pode explodir.
    # (Estourava AttributeError dentro do próprio gate `current_step`, então a pessoa nem
    # chegava a ser redirecionada pro passo do endereço: 500 na cara.)
    addr_obj = address_iface.get_by_external_id(user_ext)
    address = (
        address_iface.as_public_dict(addr_obj)
        if addr_obj is not None
        else dict.fromkeys(_ADDRESS_FIELDS)
    )
    address["missing_fields"] = [f for f in _ADDRESS_FIELDS if not address.get(f)]

    from users.roles import _address_proof

    selfie = _selfie_dict(cand)

    try:
        docs = documents_iface.get_by_external_id(user_ext)
    except NotFound:
        docs = None

    return {
        **to_dict(cand),
        "profile": profile,
        "address": address,
        "address_proof": _address_proof.section_dict(user_ext),
        "documents": docs,
        "selfie": selfie,
        "blocks": [blocks.to_dict(b) for b in blocks.get_active_blocks(cand.user)],
    }

