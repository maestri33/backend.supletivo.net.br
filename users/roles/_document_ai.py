"""Validação de documento de identidade por IA — visão + OCR + extração JSON (plan/12 + plan/15 B1).

Compartilhada: nasce no `enrollment` (RG) e atende **dois tipos** de documento — `rg` e `cnh` —
(plan/15 B1: promotor pode usar RG **ou** CNH). Uma implementação só (CONVENTION §12). Mesma
régua de 3 estados do student/selfie (plan/9): **approved** · **rejected** (motivo SEMPRE) ·
**review** (IA fora do ar OU em dúvida → o coordenador decide). Quem orquestra (status no model,
notifies, avanço do wizard) é o serviço do funil; aqui moram só as chamadas de IA.

Os valores de status espelham `RG.Validation` (pending/approved/rejected/review) — strings
compartilhadas, sem import do model (evita ciclo documents↔roles).
"""

from __future__ import annotations

import structlog
from django.conf import settings

logger = structlog.get_logger()

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
REVIEW = "review"

_AI_DOWN = "IA indisponível no momento — enviado para revisão manual do coordenador."

# Tipos de documento suportados (plan/15 B1).
DOC_RG = "rg"
DOC_CNH = "cnh"
DOC_TYPES = (DOC_RG, DOC_CNH)

# lado esperado da foto. front/back = par; full = inteiro.
_SIDE_DESC = {
    "front": (
        "a FRENTE da carteira — o lado com a FOTO do titular, a impressão digital, a assinatura "
        "e o cabeçalho (REPÚBLICA FEDERATIVA DO BRASIL / órgão emissor)"
    ),
    "back": (
        "o VERSO da carteira — o lado dos dados: REGISTRO GERAL, NOME, FILIAÇÃO, NATURALIDADE, "
        "DOC DE ORIGEM, DATA DE EXPEDIÇÃO/NASCIMENTO (no modelo antigo verde, traz a referência "
        "à 'LEI Nº 7.116 DE 29/08/83')"
    ),
    # `full` = foto ÚNICA do documento (o candidato sobe um lado só). NÃO exigir os dois lados
    # na mesma imagem: o RG antigo (cartão verde) é dobrado — cada lado é uma foto separada, é
    # impossível mostrar frente+verso num clique. Um lado legível já basta (a seção completa
    # aceita `inteira OU frente+verso`; o outro lado, quando houver, entra pelos slots front/back).
    "full": (
        "a carteira de identidade em uma foto ÚNICA — pode conter apenas UM dos lados; no "
        "modelo antigo (cartão verde), a frente OU o verso já basta, desde que os dados "
        "estejam legíveis. NÃO reprove por faltar o outro lado do documento"
    ),
}

# Por `doc_type`: como o prompt descreve o documento esperado e o que **NÃO** confundir.
# CNH-e do Victor (CNH Digital.pdf na raiz) = app gov.br: card renderizado + QR + MRZ ICAO.
_DOC_TYPE_HINT = {
    DOC_RG: (
        "uma CARTEIRA DE IDENTIDADE brasileira (RG ou a nova CIN), de qualquer modelo — inclusive "
        "o ANTIGO (cartão verde), que É um RG válido. NÃO confunda com CNH: a CNH tem elementos "
        "de HABILITAÇÃO (categoria A/B/C/D, validade, 'PERMISSÃO PARA DIRIGIR') — só trate como "
        "CNH se vir ESSES elementos."
    ),
    DOC_CNH: (
        "uma CARTEIRA NACIONAL DE HABILITAÇÃO (CNH), em qualquer modelo — inclusive a CNH-e "
        "DIGITAL (a do app gov.br: card renderizado, QR Code de validação e MRZ ICAO no rodapé). "
        "Deve ter ELEMENTOS de HABILITAÇÃO: nome do titular, nº de registro, CATEGORIA (A/B/C/D/"
        "E/ACC), VALIDADE, DATA DE NASCIMENTO, FILIAÇÃO. NÃO confunda com RG/CIN (esse não tem "
        "categoria nem validade)."
    ),
}

# Schema de extração POR TIPO (plan/15 B1). RG: campos do legado (port/12). CNH: nº/registro,
# categoria, registro nacional, validade, data de nascimento, nome, filiação.
_EXTRACT_SCHEMA_RG = (
    "{"
    '"number": "número do RG (registro geral), string ou null", '
    '"issuing_agency": "órgão emissor com UF (ex.: SSP/SP), string ou null", '
    '"issue_date": "data de expedição no formato AAAA-MM-DD ou null", '
    '"name": "nome completo do titular ou null", '
    '"birth_date": "data de nascimento no formato AAAA-MM-DD ou null", '
    '"mother_name": "nome da mãe (filiação) ou null", '
    '"father_name": "nome do pai (filiação) ou null", '
    '"birthplace": "naturalidade (cidade/UF) ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMA_CNH = (
    "{"
    '"number": "número de registro da CNH (mesmo que aparece no campo REGISTRO), string ou null", '
    '"category": "categoria da CNH (ex.: B, ACC, AB), string ou null", '
    '"national_register": "nº do registro nacional (RENACH) se visível, string ou null", '
    '"expires_on": "data de validade no formato AAAA-MM-DD ou null", '
    '"name": "nome completo do titular ou null", '
    '"birth_date": "data de nascimento no formato AAAA-MM-DD ou null", '
    '"mother_name": "nome da mãe (filiação) ou null", '
    '"father_name": "nome do pai (filiação) ou null", '
    '"name_match": "sim | nao | duvida", '
    '"name_reason": "explicação curta da comparação dos nomes"'
    "}"
)

_EXTRACT_SCHEMAS = {DOC_RG: _EXTRACT_SCHEMA_RG, DOC_CNH: _EXTRACT_SCHEMA_CNH}


def check_photo(
    image_bytes: bytes,
    *,
    side: str,
    doc_type: str = DOC_RG,
    mime_type: str = "image/jpeg",
    caller: str,
) -> tuple[str, str]:
    """Visão: a foto é mesmo o lado `side` de um `doc_type` (`rg` ou `cnh`) e está legível?
    → (status, motivo). Plan/15 B1 generalizou por `doc_type`.

    Veredito direto (padrão `_selfie`): APROVADO/REPROVADO no começo da resposta; ambíguo ou
    IA fora do ar → REVIEW (humano decide). O motivo SEMPRE volta (plan/9)."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type inválido: {doc_type!r} (use um de {DOC_TYPES})")
    if settings.TEST_EXTERNAL_ADAPTERS:
        from core.test_adapters import kyc_result

        return kyc_result()

    if not image_bytes or len(image_bytes) == 0:
        return REJECTED, "REPROVADO: Arquivo vazio ou sem conteúdo."

    if mime_type != "application/pdf" and not image_bytes.startswith(b"fake"):
        from io import BytesIO
        from PIL import Image

        try:
            img = Image.open(BytesIO(image_bytes))
            img.verify()
        except Exception:
            return REJECTED, "REPROVADO: Arquivo de imagem corrompido ou formato inválido."

    from integrations.ai import service as ai

    doc_hint = _DOC_TYPE_HINT[doc_type]
    # Regra do lado (Victor 2026-07-11): a FRENTE do RG antigo NÃO TEM dados textuais (só foto+digital+
    # assinatura) — os dados moram no VERSO. Por isso a frente NUNCA reprova por "faltam dados".
    # O lado esperado continua obrigatório; os dados só são exigidos na EXTRAÇÃO.
    is_side = side in ("front", "back")
    legibility_item = "(c)" if is_side else "(b)"
    legibility_rule = (
        f"{legibility_item} a imagem estiver tão desfocada/escura que nem dá pra ver que é este "
        "documento. "
        "ATENÇÃO: NÃO reprove porque 'faltam os dados do titular' — cada lado tem o que tem "
        "(a frente do RG antigo é só foto/digital/assinatura; os dados textuais ficam no verso). "
        "Ausência de dados NÃO é defeito nesta etapa."
        if is_side
        else f"{legibility_item} os dados estiverem genuinamente ilegíveis (muito desfocado/escuro ou cortado "
        "escondendo informação)."
    )
    side_rule = (
        "O LADO ESPERADO É OBRIGATÓRIO. (b) a imagem mostrar claramente o outro lado da carteira, "
        "mesmo que ele esteja legível; "
        if is_side
        else ""
    )
    prompt = (
        f"Esta imagem deve mostrar {_SIDE_DESC[side]} de {doc_hint} "
        "A imagem pode ter sido endireitada automaticamente; NÃO reprove por orientação/rotação. "
        "Documento plastificado costuma ter brilho/reflexo — só é problema se ESCONDER os dados. "
        f"Reprove APENAS se: (a) não for {doc_type.upper()} válido (outro documento, QR code, "
        f"selfie, outro papel); {side_rule}ou {legibility_rule} Responda em português começando "
        "OBRIGATORIAMENTE com APROVADO "
        "ou REPROVADO, seguida de um motivo curto e claro."
    )
    try:
        desc = ai.describe_image(
            image_bytes, caller=caller, mime_type=mime_type, prompt=prompt
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar → review (coordenador resolve)
        logger.warning("document_ai.vision_failed", caller=caller, error=str(exc)[:200])
        return REVIEW, _AI_DOWN
    head = (desc or "").strip().upper()[:24]
    if "REPROVADO" in head:  # antes de APROVADO — "REPROVADO" contém "APROVADO"
        return REJECTED, desc
    if "APROVADO" in head:
        return APPROVED, desc
    return REVIEW, desc or "IA não foi conclusiva — enviado para revisão manual."


def fix_orientation(
    image_path: str, *, mime_type: str = "image/jpeg", caller: str
) -> bool:
    """Endireita a foto pela orientação EXIF do celular (decisão do Victor 2026-06-11: tratar a
    imagem antes de validar). REGRAVA reta no mesmo arquivo (formato preservado). Retorna se mudou.

    Só EXIF (de propósito): é o que o celular grava ao fotografar de lado, resolve o caso real e é
    determinístico. NÃO tentamos adivinhar rotação de imagem SEM EXIF — a visão e o OCR (Google
    Vision) leem o documento em qualquer orientação, então endireitar é melhoria de UX/biometria,
    não pré-requisito da validação. Best-effort: erro → não mexe na imagem."""
    from pathlib import Path

    from PIL import Image, ImageOps

    try:
        img = Image.open(image_path)
        exif = img.getexif()
        orientation = exif.get(0x0112, 1)  # tag Orientation; 1 = normal (nada a fazer)
        if orientation == 1:
            return False
        fixed = ImageOps.exif_transpose(img).convert("RGB")
        fmt = "PNG" if Path(image_path).suffix.lower() == ".png" else "JPEG"
        save_kwargs = {"quality": 90} if fmt == "JPEG" else {}
        fixed.save(image_path, format=fmt, **save_kwargs)
        logger.info(
            "document_ai.orientation_fixed", caller=caller, exif_orientation=orientation
        )
        return True
    except Exception as exc:  # noqa: BLE001 — endireitar é apoio; nunca quebra o pipeline
        logger.warning(
            "document_ai.fix_orientation_failed", caller=caller, error=str(exc)[:200]
        )
        return False


def ocr_images(images: list[bytes], *, caller: str) -> str:
    """OCR (Google Vision, modo documento) de cada imagem; devolve o texto junto."""
    if settings.TEST_EXTERNAL_ADAPTERS:
        from core.test_adapters import document_ocr

        return document_ocr()
    from integrations.ai import service as ai

    parts = [ai.ocr(img, caller=caller, document=True) for img in images]
    return "\n\n--- PRÓXIMA IMAGEM ---\n\n".join(p for p in parts if p)


def extract_rg(ocr_text: str, *, holder_name: str | None, caller: str) -> dict:
    """Wrapper de retrocompatibilidade (plan/12) — delega pra `extract_document(..., doc_type="rg")`.
    Mantido pra não quebrar callers existentes; novos callers devem usar `extract_document`."""
    return extract_document(
        ocr_text, doc_type=DOC_RG, holder_name=holder_name, caller=caller
    )


def extract_document(
    ocr_text: str,
    *,
    doc_type: str,
    holder_name: str | None,
    caller: str,
) -> dict:
    """1 chamada LLM (JSON): extrai os campos do documento (`rg` ou `cnh`) + confere o nome do
    titular. Plan/15 B1 — generalizou `extract_rg` por `doc_type`.

    `name_match`: 'sim' = mesmo titular (variação por CASAMENTO — sobrenome acrescentado/
    alterado — ou abreviação conta como 'sim'); 'nao' = claramente OUTRA pessoa; 'duvida' =
    ilegível/incompleto. A IA não inventa: campo ausente no OCR = null. Erro de IA sobe
    (o orquestrador decide o que fazer — em regra, REVIEW)."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type inválido: {doc_type!r} (use um de {DOC_TYPES})")
    if settings.TEST_EXTERNAL_ADAPTERS:
        from core.test_adapters import document_extract

        return document_extract(doc_type=doc_type, holder_name=holder_name)
    from integrations.ai import service as ai

    expected = holder_name or "(nome não informado)"
    schema = _EXTRACT_SCHEMAS[doc_type]
    if doc_type == DOC_CNH:
        doc_label = "carteira nacional de habilitação (CNH)"
        instruction = (
            "Você extrai dados da Carteira Nacional de Habilitação brasileira (CNH, inclusive "
            "a CNH-e digital do app gov.br: card + QR + MRZ) a partir de texto OCR. "
            "Responda APENAS o JSON pedido."
        )
    else:
        doc_label = "carteira de identidade brasileira (RG/CIN)"
        instruction = (
            "Você extrai dados de carteiras de identidade brasileiras (RG/CIN) a partir de "
            "texto OCR. Responda APENAS o JSON pedido."
        )
    prompt = (
        f"Texto OCR de uma {doc_label}:\n\n{ocr_text}\n\n"
        f"O titular esperado desta conta é: {expected}.\n"
        "Compare o nome impresso no documento com o esperado: variações por CASAMENTO "
        "(sobrenome acrescentado, removido ou alterado) ou abreviações contam como 'sim', "
        "desde que seja claramente a MESMA pessoa; nome de OUTRA pessoa = 'nao'; nome "
        "ilegível ou ausente no texto = 'duvida'. Explique a comparação em name_reason. "
        "NÃO invente: qualquer campo que não estiver no texto = null."
    )
    data = ai.generate_json(
        prompt,
        caller=caller,
        instruction=instruction,
        schema_description=schema,
    )
    if not isinstance(data, dict):
        data = {}
    return data

