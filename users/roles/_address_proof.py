"""Validação do COMPROVANTE DE ENDEREÇO por IA (F1, Victor 2026-07-08) — compartilhada por
`candidate` e `enrollment`.

Reusa o pipeline de visão+OCR+extração do `student` (chaveado por `doc_type="address_proof"`) — NÃO
tem IA própria. O que é NOVO aqui é o comparador `_address_matches`: o student só confere o titular
(`name_match`), nunca o ENDEREÇO extraído contra o informado. Aqui somamos as duas checagens.

Estados (espelham `_document_ai`, + um):
  • approved      — endereço bate + titular bate (name_match=sim)
  • rejected      — visão falha OU endereço não bate com o informado (peça pra corrigir/reenviar)
  • review        — IA em dúvida (name_match=duvida / IA fora do ar) → coordenador decide
  • needs_kinship — endereço bate mas o titular é OUTRO (name_match=nao): NÃO reprova; pede o grau
                    de parentesco (cônjuge/pai/mãe...) e libera depois ("não importa quem seja, mas
                    temos que saber pra não virar baderna").

# ponytail: `_address_matches` é heurística fuzzy (sem parsing oficial de CEP). Permissivo de
# propósito — só reprova em divergência CLARA de CEP ou cidade, nunca por typo de rua. Todo veredito
# é logado; se falso-negativo aparecer, sobe o limiar. Upgrade path: validar CEP no ViaCEP.
"""

from __future__ import annotations

import re
import unicodedata

import structlog

logger = structlog.get_logger()

APPROVED = "approved"
REJECTED = "rejected"
REVIEW = "review"
NEEDS_KINSHIP = "needs_kinship"

_DOC_TYPE = "address_proof"


def _norm(s: str | None) -> str:
    """minúsculo, sem acento, colapsa espaços — pra comparar rua/cidade sem falso-negativo bobo."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


# Conectivos que não contam como sobrenome na comparação de família.
_NAME_STOPWORDS = {"de", "da", "do", "das", "dos", "e"}


def _surnames(name: str | None) -> set[str]:
    """Sobrenomes de um nome (tudo menos o primeiro nome, sem conectivos), normalizados."""
    parts = [p for p in _norm(name).split(" ") if p and p not in _NAME_STOPWORDS]
    return set(parts[1:])


def _same_person(a: str | None, b: str | None) -> bool:
    """Mesma pessoa por comparação frouxa: nomes normalizados iguais, ou um contém o outro
    (comprovante costuma abreviar/cortar). Não tenta ser esperto: o caso duvidoso não passa."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _address_matches(extracted: dict, address) -> tuple[bool, str]:
    """O endereço extraído do comprovante bate com o `Address` informado? (bool, motivo).

    Regra permissiva: reprova só se CEP OU cidade divergirem CLARAMENTE (ambos presentes e diferentes).
    A rua entra como reforço (overlap de tokens), não como veto isolado — comprovante abrevia/varia
    logradouro demais pra travar por isso. Campo ausente = não penaliza (dá o benefício da dúvida)."""
    if address is None or not any(
        getattr(address, field, None) for field in ("zipcode", "street", "city")
    ):
        return True, "Endereço será preenchido a partir do comprovante."

    ex_zip = _digits(extracted.get("zip"))
    in_zip = _digits(getattr(address, "zipcode", None))
    if ex_zip and in_zip and ex_zip != in_zip:
        return False, f"CEP do comprovante ({ex_zip}) difere do informado ({in_zip})."

    ex_city = _norm(extracted.get("city"))
    in_city = _norm(getattr(address, "city", None))
    if ex_city and in_city and ex_city != in_city:
        return (
            False,
            f"Cidade do comprovante ({ex_city}) difere da informada ({in_city}).",
        )

    # reforço leve: se CEP e cidade nada disseram (ambos ausentes de um lado), a rua precisa ao menos
    # tocar. Só reprova se houver rua nos dois lados e ZERO palavra em comum.
    ex_street = set(_norm(extracted.get("street")).split())
    in_street = set(_norm(getattr(address, "street", None)).split())
    if not (ex_zip and in_zip) and not (ex_city and in_city):
        if ex_street and in_street and ex_street.isdisjoint(in_street):
            return (
                False,
                "Nem CEP, nem cidade, nem rua bateram com o endereço informado.",
            )

    return True, "Endereço confere com o informado."


def run_validation(
    image_bytes: bytes,
    *,
    address,
    holder_name: str | None,
    mother_name: str | None = None,
    father_name: str | None = None,
    mime_type: str = "image/jpeg",
    caller: str,
) -> tuple[str, dict]:
    """Valida 1 comprovante: visão → (endereço bate?) → titularidade em camadas. Devolve
    (status, payload). Payload guarda `vision`, `extracted`, `address_match`, `reason` e
    `kinship_kind` quando o titular é outra pessoa.

    Titularidade (Victor 2026-07-28): o próprio → ok; **pai ou mãe** (filiação que o RG já
    populou) → ok direto, ninguém pergunta parentesco do próprio pai; **sobrenome em comum**
    → confirmar o grau de parentesco (`kinship_kind="confirm"`); **nome totalmente diferente**
    → justificar por que mora ali (`kinship_kind="justify"`)."""
    from users.roles.student import _document_ai as doc_ai

    # (a) Visão: é um comprovante de endereço legível?
    vision_status, vision_reason = doc_ai.check_student_document_photo(
        image_bytes, doc_type=_DOC_TYPE, mime_type=mime_type, caller=caller
    )
    result: dict = {"vision": {"status": vision_status, "reason": vision_reason}}
    if vision_status == doc_ai.REJECTED:
        result["reason"] = vision_reason
        return REJECTED, result
    if vision_status != doc_ai.APPROVED:
        result["reason"] = vision_reason
        return REVIEW, result

    # (b) OCR + extração (endereço + titular).
    try:
        ocr_text = doc_ai.ocr_image(image_bytes, caller=caller)
        extracted = doc_ai.extract_student_document(
            ocr_text, doc_type=_DOC_TYPE, holder_name=holder_name, caller=caller
        )
    except Exception as exc:  # noqa: BLE001 — IA fora na extração → review
        logger.warning(
            "address_proof.extract_failed", caller=caller, error=str(exc)[:200]
        )
        result["reason"] = (
            "IA indisponível na extração — enviado para revisão manual do coordenador."
        )
        return REVIEW, result
    result["extracted"] = extracted

    # (c) endereço: no fluxo comprovante-PRIMEIRO (Victor 2026-07-28) não há nada digitado —
    # o extraído VIRA o endereço (quem popula é o orquestrador). Só comparamos quando o
    # endereço informado já existe completo (aluno digitou antes / outro funil): aí divergência
    # continua reprovando, porque o comprovante deixa de provar o endereço cadastrado.
    from users.address import service as address_svc

    if address is not None and address_svc.is_complete(address):
        addr_ok, addr_reason = _address_matches(extracted, address)
        result["address_match"] = {"ok": addr_ok, "reason": addr_reason}
        logger.info(
            "address_proof.address_match", caller=caller, ok=addr_ok, reason=addr_reason
        )
        if not addr_ok:
            result["reason"] = (
                f"O endereço do comprovante não confere com o informado. {addr_reason} "
                "Corrija o endereço ou envie um comprovante do endereço cadastrado."
            )
            return REJECTED, result

    # (d) titularidade em camadas (docstring): próprio → pai/mãe → sobrenome → estranho.
    match = str(extracted.get("name_match") or "").strip().lower()
    name_reason = (extracted.get("name_reason") or "").strip()
    holder = str(extracted.get("holder_name") or "").strip()
    if match in ("sim", "yes"):
        result["reason"] = name_reason or "Comprovante validado."
        return APPROVED, result
    if match in ("nao", "não", "no"):
        # Pai/mãe ANTES de perguntar qualquer coisa: a filiação veio do RG (fonte oficial),
        # comprovante no nome deles é o arranjo mais comum do público-alvo.
        for parent, label in ((mother_name, "mãe"), (father_name, "pai")):
            if _same_person(holder, parent):
                result["reason"] = (
                    f"Comprovante no nome da {label} do titular — filiação confere com o RG."
                    if label == "mãe"
                    else "Comprovante no nome do pai do titular — filiação confere com o RG."
                )
                return APPROVED, result
        if holder and _surnames(holder) & _surnames(holder_name):
            # Sobrenome em comum: provável família — só falta o GRAU.
            result["kinship_kind"] = "confirm"
            result["reason"] = (
                f"O comprovante está no nome de {holder}, que tem sobrenome em comum com o "
                f"titular. Confirmar o grau de parentesco. {name_reason}".strip()
            )
            return NEEDS_KINSHIP, result
        # Nome totalmente diferente: precisa JUSTIFICAR o vínculo com o endereço.
        result["kinship_kind"] = "justify"
        result["reason"] = (
            f"O titular do comprovante ({holder or 'não identificado'}) não tem relação "
            f"aparente com o cadastro. Justificar o vínculo. {name_reason}".strip()
        )
        return NEEDS_KINSHIP, result
    # duvida / ilegível → coordenador decide
    result["reason"] = f"Não deu pra confirmar o titular. {name_reason}".strip()
    return REVIEW, result


def _mime_of(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return "image/png" if ext == "png" else "image/jpeg"


def validate_and_store(user_external_id: str, *, caller: str) -> str:
    """Orquestração compartilhada (candidate/enrollment): lê a foto do comprovante já salva, roda a
    IA (endereço + titular), grava o veredito no `AddressProof` e devolve o status. Idempotente e
    best-effort: sem foto/perfil/endereço → `review` (nunca reprova no escuro). Chamada na task async."""
    from pathlib import Path

    from django.conf import settings
    from django.utils import timezone

    from users.address import interface as address_iface
    from users.documents import service as documents_iface
    from users.profiles import interface as profiles

    ap = documents_iface.get_address_proof(user_external_id)
    if ap is None or not ap.photo:
        return REVIEW
    fp = Path(settings.MEDIA_ROOT) / ap.photo
    if not fp.exists():
        return REVIEW
    p = profiles.find_by_external_id(user_external_id)
    address = p.address if p else None
    holder_name = p.name if p else None

    status, payload = run_validation(
        fp.read_bytes(),
        address=address,
        holder_name=holder_name,
        mother_name=p.mother_name if p else None,
        father_name=p.father_name if p else None,
        mime_type=_mime_of(ap.photo),
        caller=caller,
    )
    extracted = payload.get("extracted") if isinstance(payload, dict) else None
    if p is not None and isinstance(extracted, dict):
        try:
            address_iface.fill_empty(
                external_id=user_external_id,
                zipcode=extracted.get("zip") or extracted.get("zipcode"),
                street=extracted.get("street"),
                number=extracted.get("number"),
                complement=extracted.get("complement"),
                neighborhood=extracted.get("neighborhood"),
                city=extracted.get("city"),
                state=extracted.get("state"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "address_proof.address_fill_failed", caller=caller, error=str(exc)[:200]
            )
    ap.validation_status = status
    ap.validation_result = payload
    ap.validated_at = timezone.now()
    ap.save(update_fields=["validation_status", "validation_result", "validated_at"])
    if status in (APPROVED, NEEDS_KINSHIP):
        # Comprovante-PRIMEIRO (Victor 2026-07-28): o endereço extraído POPULA o cadastro —
        # o formulário vira confirmação (número/complemento), não digitação. Só campos vazios:
        # o que a pessoa já corrigiu à mão não é sobrescrito. `needs_kinship` também popula
        # (a dúvida é sobre o TITULAR; o endereço extraído é o mesmo).
        _fill_address_from_extracted(
            user_external_id, payload.get("extracted") or {}, caller=caller
        )
    logger.info("address_proof.validated", caller=caller, status=status)

    # ponytail: o signal post_save do AddressProof cria o bloco (rejected) ou resolve (approved/pending).
    # Notify explícito só em rejeição (a aprovação o usuário descobre pelo /me normal).
    if status == REJECTED and p is not None:
        try:
            from notify.interface.events import send_event

            send_event(
                "enrollment.address_proof_rejected",
                profile=p,
                subject="Seu comprovante de endereço precisa de ajuste",
                body_md_override=payload.get("reason", "")[:400],
            )
        except Exception:  # noqa: BLE001
            logger.warning("address_proof.notify_failed", caller=caller, status=status)

    return status


_EXTRACT_TO_ADDRESS = {
    "street": "street",
    "number": "number",
    "complement": "complement",
    "neighborhood": "neighborhood",
    "city": "city",
    "state": "state",
    "zip": "zipcode",
}


def _fill_address_from_extracted(
    user_external_id: str, extracted: dict, *, caller: str
) -> None:
    """Popula SÓ campos vazios do Address (`fill_empty`) com o que a IA extraiu do comprovante.
    Best-effort: falha aqui não derruba o veredito (o aluno completa o que faltar na tela)."""
    from users.address import service as address_svc

    try:
        fields = {}
        for src, dst in _EXTRACT_TO_ADDRESS.items():
            value = extracted.get(src)
            if value in (None, ""):
                continue
            value = _digits(value)[:8] if dst == "zipcode" else str(value).strip()
            if value:
                fields[dst] = value
        if fields:
            address_svc.fill_empty(external_id=user_external_id, **fields)
            logger.info(
                "address_proof.address_filled", caller=caller, fields=sorted(fields)
            )
    except Exception as exc:  # noqa: BLE001 — enfeite falhou, veredito fica
        logger.warning(
            "address_proof.address_fill_failed", caller=caller, error=str(exc)[:200]
        )


def submit_kinship(user_external_id: str, relation: str) -> str:
    """Titular diferente (`needs_kinship`): a pessoa explica quem é / o parentesco. Grava e libera
    (→ approved). Só age se estava em `needs_kinship`. Devolve o novo status."""
    from django.utils import timezone

    from users.documents import service as documents_iface

    ap = documents_iface.get_address_proof(user_external_id)
    if ap is None:
        return REVIEW
    if ap.validation_status != NEEDS_KINSHIP:
        return ap.validation_status
    relation = (relation or "").strip()
    if not relation:
        return NEEDS_KINSHIP  # sem explicação → continua pendente
    # IA avalia se a explicação tem FUNDAMENTO e corrige o português. Sem fundamento (lixo/sem
    # sentido) → NÃO aprova; volta pra pessoa reescrever (human-in-the-loop). Fail-open dentro da IA.
    from integrations.ai import service as ai

    verdict = ai.evaluate_kinship(relation, caller="address_proof.kinship")
    if not verdict.get("has_merit"):
        return NEEDS_KINSHIP
    ap.kinship_relation = verdict.get("corrected") or relation
    ap.kinship_provided_at = timezone.now()
    ap.validation_status = APPROVED
    ap.save(
        update_fields=[
            "kinship_relation",
            "kinship_provided_at",
            "validation_status",
        ]
    )
    logger.info("address_proof.kinship_submitted", relation=ap.kinship_relation[:80])
    return APPROVED


def decide_kinship(user_external_id: str, *, approve: bool, reason: str | None) -> str:
    """Coordenador decide sobre a justificativa de titularidade (Victor 2026-07-28).

    Aprovou → o comprovante vale como está. Rejeitou → `rejected` com a flag
    `needs_new_proof`: a tela do aluno TRAVA no comprovante pedindo outro documento — de
    preferência no nome dele — e só destrava com um novo upload (que re-arma `pending` e
    derruba a flag). O motivo do coordenador fica no `validation_result` (interno)."""
    from django.utils import timezone

    from users.documents import service as documents_iface

    ap = documents_iface.get_address_proof(user_external_id)
    if ap is None:
        return REVIEW
    result = ap.validation_result or {}
    if approve:
        ap.validation_status = APPROVED
        result["kinship_decided"] = {"approve": True, "reason": (reason or "").strip()}
    else:
        ap.validation_status = REJECTED
        result["needs_new_proof"] = True
        result["kinship_decided"] = {"approve": False, "reason": (reason or "").strip()}
    ap.validation_result = result
    ap.validated_at = timezone.now()
    ap.save(update_fields=["validation_status", "validation_result", "validated_at"])
    logger.info("address_proof.kinship_decided", approve=approve)
    return ap.validation_status


def is_approved(user_external_id: str) -> bool:
    """Gate do wizard: o comprovante está aprovado? (usado no `_advance_address` dos dois funis)."""
    from users.documents import service as documents_iface

    ap = documents_iface.get_address_proof(user_external_id)
    return bool(ap and ap.validation_status == APPROVED)


def _public_reason(status: str | None, result: dict) -> str | None:
    """O que o ALUNO lê — orientação, nunca o critério (mesma régua do RG, Victor 2026-07-28).
    O motivo real (titular X, endereço divergente, justificativa rejeitada) fica no
    `validation_result`, que só o hub/staff enxerga."""
    if status == REJECTED:
        if result.get("needs_new_proof"):
            return (
                "Precisamos de outro comprovante de residência — de preferência no SEU nome "
                "(conta de luz, água, internet ou telefone dos últimos 90 dias)."
            )
        return (
            "Não deu pra validar esse comprovante. Manda outro: foto nítida, documento "
            "recente (últimos 90 dias) e com o endereço completo aparecendo."
        )
    if status == NEEDS_KINSHIP:
        kind = result.get("kinship_kind")
        holder = str((result.get("extracted") or {}).get("holder_name") or "").strip()
        quem = holder or "outra pessoa"
        if kind == "confirm":
            return f"O comprovante está no nome de {quem}. Confirma pra gente o grau de parentesco?"
        return f"O comprovante está no nome de {quem}. Conta pra gente qual é o seu vínculo com esse endereço?"
    if status == REVIEW:
        return "Seu comprovante foi pra conferência da coordenação — a gente te avisa assim que sair."
    return None


def section_dict(user_external_id: str) -> dict:
    """Bloco do comprovante pro /me e GET (status + motivo público + parentesco).
    `exists`=False = não enviado. `needs_new_proof` trava a tela do aluno no upload."""
    from users.documents import service as documents_iface

    ap = documents_iface.get_address_proof(user_external_id)
    if ap is None or not ap.photo:
        return {
            "exists": False,
            "photo": None,
            "status": None,
            "reason": None,
            "needs_kinship": False,
            "kinship_kind": None,
            "kinship_relation": None,
            "needs_new_proof": False,
        }
    result = ap.validation_result if isinstance(ap.validation_result, dict) else {}
    return {
        "exists": True,
        "photo": ap.photo,
        "status": ap.validation_status,
        "reason": _public_reason(ap.validation_status, result),
        "needs_kinship": ap.validation_status == NEEDS_KINSHIP,
        "kinship_kind": result.get("kinship_kind")
        if ap.validation_status == NEEDS_KINSHIP
        else None,
        "kinship_relation": ap.kinship_relation,
        # nome do titular lido do comprovante — a tela de parentesco diz DE QUEM é a conta
        # em vez de "outra pessoa" genérico.
        "holder_name": (result.get("extracted") or {}).get("holder_name")
        or result.get("holder_name"),
        "needs_new_proof": bool(
            ap.validation_status == REJECTED and result.get("needs_new_proof")
        ),
    }
