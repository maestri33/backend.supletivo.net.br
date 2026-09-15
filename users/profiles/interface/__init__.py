"""Superfície pública in-process do `profiles` (CONVENTION §3): o que o auth (e futuros apps) chamam.

Escopo mínimo: criação do Profile + lookups de unicidade/contato. Sem service separado — o Profile
ainda é só dados; quando o `profiles` completo chegar (Pix/Asaas, address), a lógica vira `service.py`.
"""

from __future__ import annotations

from users.profiles.models import Profile


def exists_cpf(cpf: str) -> bool:
    return Profile.objects.filter(cpf=cpf).exists()


def phone_variants(phone: str) -> list[str]:
    """Canônico + a outra forma do 9º dígito (BR), na ordem: o que veio primeiro.

    O número é GRAVADO como o WhatsApp o resolve (`resolve_br_number`), e para boa parte
    dos DDDs isso é a forma CURTA (`554299384069`); mas o usuário digita a forma que ele
    conhece, com o 9 (`5542999384069`). Comparar cru trancava o dono da conta do lado de
    fora: o `check` não achava, o `register` achava e estourava `PHONE_EXISTS`, e o app só
    sabia dizer "problema no nosso servidor" (E2E 2026-07-28 — aconteceu com uma matrícula
    JÁ PAGA). Só celular: fixo (8 dígitos que não começam com 9) não tem essa dualidade.
    """
    digits = "".join(c for c in phone if c.isdigit())
    if not digits.startswith("55") or len(digits) not in (12, 13):
        return [digits]
    ddd, local = digits[2:4], digits[4:]
    if len(local) == 9 and local.startswith("9"):
        return [digits, f"55{ddd}{local[1:]}"]
    if len(local) == 8 and local[0] in "6789":
        return [digits, f"55{ddd}9{local}"]
    return [digits]


def exists_phone(phone: str) -> bool:
    return Profile.objects.filter(phone__in=phone_variants(phone)).exists()


def exists_email(email: str) -> bool:
    return Profile.objects.filter(email=email).exists()


def find_by_email(email: str) -> Profile | None:
    return Profile.objects.filter(email=email).select_related("user").first()



def find_by_cpf(cpf: str) -> Profile | None:
    return Profile.objects.filter(cpf=cpf).select_related("user").first()


def find_by_phone(phone: str) -> Profile | None:
    """Acha pelo número em QUALQUER das duas formas do 9º dígito (ver `phone_variants`)."""
    variants = phone_variants(phone)
    found = {
        p.phone: p
        for p in Profile.objects.filter(phone__in=variants).select_related("user")
    }
    # A forma exata ganha; a variante é o resgate de quem digitou a outra.
    for v in variants:
        if v in found:
            return found[v]
    return None


def find_by_external_id(external_id: str) -> Profile | None:
    """Profile pelo external_id do User (uso de borda, §4)."""
    return (
        Profile.objects.filter(user__external_id=external_id)
        .select_related("user", "address")
        .first()
    )


def get(user) -> Profile | None:
    """Profile do User (ou None se ainda não tem)."""
    return Profile.objects.filter(user=user).first()


_IDENTITY_FIELDS = (
    "name",
    "birth_date",
    "mother_name",
    "father_name",
    "marital_status",
    "nationality",
    "birthplace",
    "pix_key",
    "pix_key_type",
)


def fill_identity(user, **fields) -> Profile | None:
    """Grava campos de IDENTIDADE no Profile — o lugar ÚNICO da pessoa (Victor 2026-06-16). SÓ os
    que estão VAZIOS (não sobrescreve o que já existe). Usado pelo `set_profile`, pela extração do
    OCR do documento e pela validação do Pix. Ignora chaves desconhecidas e valores None."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    changed = []
    for field, value in fields.items():
        if (
            field in _IDENTITY_FIELDS
            and value is not None
            and not getattr(p, field, None)
        ):
            setattr(p, field, value)
            changed.append(field)
    if changed:
        p.save(update_fields=[*changed, "updated_at"])
    return p


def update_identity(user, **fields) -> Profile | None:
    """Atualiza campos de IDENTIDADE no Profile — SOBRESCREVE (correção do usuário/coordenador). Par
    do `fill_identity` (que só preenche vazios). Ignora chaves desconhecidas e valores None."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    changed = []
    for field, value in fields.items():
        if field in _IDENTITY_FIELDS and value is not None:
            setattr(p, field, value)
            changed.append(field)
    if changed:
        p.save(update_fields=[*changed, "updated_at"])
    return p


def get_map(users) -> dict:
    """Profiles de vários Users numa query só — evita N+1 nas listagens. Devolve `{user_id: Profile}`."""
    return {p.user_id: p for p in Profile.objects.filter(user__in=list(users))}


def create(
    *,
    user,
    cpf: str | None,
    phone: str,
    email: str | None = None,
    gender: str | None = None,
    name: str | None = None,
    birth_date=None,
) -> Profile:
    """Cria o Profile 1-1 do User. Chamado DENTRO da transação atômica do register (auth).

    `name`/`birth_date` chegam do CPFHub (brinde da validação de identidade). O `address` é
    vinculado depois, no mesmo provisionamento, via `attach_address` (Address nasce vazio).
    """
    return Profile.objects.create(
        user=user,
        cpf=cpf,
        phone=phone,
        email=email,
        gender=gender,
        name=name,
        birth_date=birth_date,
    )


def attach_address(profile: Profile, address) -> Profile:
    """Liga o Profile a um Address (Profile→Address, §4). Usado no provisionamento (auth)."""
    profile.address = address
    profile.save(update_fields=["address"])
    return profile


def get_address(external_id: str):
    """Endereço do usuário (via `profile.address`), ou None."""
    profile = find_by_external_id(external_id)
    return profile.address if profile else None


def set_pix(
    external_id: str, pix_key: str, pix_key_type: str | None = None
) -> Profile | None:
    """Grava a chave Pix (+ tipo) no profile — o lugar canônico (finance usa no payout)."""
    profile = find_by_external_id(external_id)
    if profile is None:
        return None
    profile.pix_key = pix_key
    fields = ["pix_key"]
    if pix_key_type is not None:
        profile.pix_key_type = pix_key_type
        fields.append("pix_key_type")
    profile.save(update_fields=fields)
    return profile


def set_education(
    user,
    *,
    level: str,
    completed: bool,
    grade: int | None = None,
    last_completed_grade: int | None = None,
    qualification: str | None = None,
    last_completed_qualification: str | None = None,
    education_status: str | None = None,
    year: int | None = None,
    city: str | None = None,
    school: str | None = None,
) -> Profile | None:
    """Grava escolaridade estruturada no Profile e permite correção posterior."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    p.education_level = level
    p.education_completed = completed
    p.education_grade = grade
    p.education_last_completed_grade = last_completed_grade
    p.education_qualification = qualification
    p.education_last_completed_qualification = last_completed_qualification
    p.education_status = education_status
    p.education_year = year
    p.education_city = city
    p.education_school = school
    p.save(
        update_fields=[
            "education_level",
            "education_completed",
            "education_grade",
            "education_last_completed_grade",
            "education_qualification",
            "education_last_completed_qualification",
            "education_status",
            "education_year",
            "education_city",
            "education_school",
            "updated_at",
        ]
    )
    return p


def has_medio_completo(user) -> bool:
    """Ensino médio COMPLETO? (decide `Promoter.pre_matriculado`). Sem profile / sem dado → False
    (na dúvida, pré-matriculado — o promotor sem médio confirmado entra no fluxo diferenciado)."""
    p = Profile.objects.filter(user=user).first()
    return bool(
        p
        and (
            p.education_level == "superior"
            or (p.education_level == "medio" and p.education_completed)
        )
    )


def set_selfie_needs_meeting(user, value: bool = True) -> Profile | None:
    """Flag nível-pessoa (F2): selfie reprovou 5× → exige encontro presencial no fim do curso.
    Vive no Profile p/ sobreviver candidate→promoter→enrollment→student. None se não tem profile."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    p.selfie_needs_meeting = value
    p.save(update_fields=["selfie_needs_meeting", "updated_at"])
    return p


def set_email(user, email: str) -> Profile | None:
    """Grava o e-mail de contato no profile (passo 5 do funil do lead v2). None se não tem profile.

    A UNICIDADE é checada pelo caller (`auth.set_email` → EMAIL_CONFLICT) antes de gravar; o
    `unique` do banco segue como última linha de defesa."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    p.email = email
    p.save(update_fields=["email", "updated_at"])
    return p


def set_cpf_identity(
    user, *, cpf: str, name=None, gender=None, birth_date=None
) -> Profile | None:
    """Grava o CPF + identidade (CPFHub) no profile — passo 3 do funil do lead v2 (a conta nasce
    sem CPF no passo do telefone). Identidade só PREENCHE vazios (mesma régua do `fill_identity`);
    o CPF é estritamente IMUTÁVEL após confirmado e validado. None se não tem profile."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    if p.cpf and p.cpf != cpf:
        from users.exceptions import Conflict

        raise Conflict("CPF já confirmado nesta conta e não pode ser alterado.", code="CPF_ALREADY_SET")
    changed = []
    if not p.cpf:
        p.cpf = cpf
        changed.append("cpf")
    if name and not p.name:
        p.name = name
        changed.append("name")
    if gender and not p.gender:
        p.gender = gender
        changed.append("gender")
    if birth_date and not p.birth_date:
        p.birth_date = birth_date
        changed.append("birth_date")
    if changed:
        p.save(update_fields=[*changed, "updated_at"])
    return p


def set_phone(user, phone: str) -> Profile | None:
    """Grava o telefone de login no profile — usado pelo resgate do staff (`auth.change_phone`)
    quando o usuário perde o número e fica trancado fora do OTP. None se não tem profile."""
    p = Profile.objects.filter(user=user).first()
    if p is None:
        return None
    p.phone = phone
    p.save(update_fields=["phone", "updated_at"])
    return p


__all__ = [
    "exists_cpf",
    "exists_phone",
    "exists_email",
    "find_by_cpf",
    "find_by_phone",
    "find_by_external_id",
    "get",
    "get_map",
    "create",
    "set_email",
    "set_cpf_identity",
    "attach_address",
    "get_address",
    "set_pix",
    "set_phone",
    "set_education",
    "has_medio_completo",
    "set_selfie_needs_meeting",
]
