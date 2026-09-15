"""IA de visão + OCR + extração JSON para documentos do `student`.

Espelha a arquitetura de `users.roles._document_ai` (pipeline 2 estágios:
visão → OCR+extração), mas adaptada para os tipos de documento do aluno
(`StudentDocument.Type`).

Cada documento do aluno tem SÓ 1 foto. A decisão final é:
  • REPROVADO se a visão reprovar;
  • REVIEW se a IA falhar, estiver em dúvida, ou a extração não confirmar identidade;
  • APROVADO só quando visão + extração de identidade baterem.
"""

from __future__ import annotations

import structlog

from users.roles.student import config

logger = structlog.get_logger()

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
REVIEW = "review"

_AI_DOWN = "IA indisponível no momento — enviado para revisão manual do coordenador."

DOC_TYPES = tuple(config.EXTRACT_SCHEMAS.keys())


def check_student_document_photo(
    image_bytes: bytes,
    *,
    doc_type: str,
    mime_type: str = "image/jpeg",
    caller: str,
) -> tuple[str, str]:
    """Visão: a foto é mesmo o tipo de documento esperado e está legível?

    Retorna (status, motivo). Veredito direto: APROVADO/REPROVADO no começo da
    resposta; ambíguo ou IA fora do ar → REVIEW (humano decide)."""
    if doc_type not in DOC_TYPES:
        return REVIEW, f"Tipo de documento não suportado pela IA: {doc_type!r}"

    from integrations.ai import service as ai

    hint = config.doc_type_hint(doc_type)
    prompt = (
        f"Esta imagem deve mostrar {hint}. "
        "A imagem pode ter sido endireitada automaticamente; NÃO reprove por orientação/rotação. "
        "Documento plastificado costuma ter brilho/reflexo — só é problema se ESCONDER os dados. "
        "Reprove APENAS se: (a) não for o documento esperado (outro papel, selfie, tela de celular, "
        "QR code genérico) — ou (b) os dados estiverem genuinamente ilegíveis (muito desfocado/escuro "
        "ou cortado escondendo informação). Responda em português começando OBRIGATORIAMENTE com "
        "APROVADO ou REPROVADO, seguida de um motivo curto e claro."
    )
    try:
        desc = ai.describe_image(
            image_bytes, caller=caller, mime_type=mime_type, prompt=prompt
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar → review
        logger.warning(
            "student_doc_ai.vision_failed", caller=caller, error=str(exc)[:200]
        )
        return REVIEW, _AI_DOWN
    head = (desc or "").strip().upper()[:24]
    if "REPROVADO" in head:  # antes de APROVADO — "REPROVADO" contém "APROVADO"
        return REJECTED, desc
    if "APROVADO" in head:
        return APPROVED, desc
    return REVIEW, desc or "IA não foi conclusiva — enviado para revisão manual."


def ocr_image(
    image_bytes: bytes,
    *,
    caller: str,
) -> str:
    """OCR de 1 foto; devolve o texto bruto. Reutiliza o helper multi-imagem do módulo compartilhado."""
    from users.roles import _document_ai

    return _document_ai.ocr_images([image_bytes], caller=caller)


def extract_student_document(
    ocr_text: str,
    *,
    doc_type: str,
    holder_name: str | None,
    caller: str,
) -> dict:
    """1 chamada LLM (JSON): extrai campos relevantes do documento do aluno + confere nome do titular.

    `name_match`: 'sim' = mesmo titular (variação por casamento/abreviação); 'nao' = claramente
    outra pessoa; 'duvida' = ilegível/incompleto. A IA não inventa: campo ausente no OCR = null.
    Erro de IA sobe (quem orquestra decide REVIEW)."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type inválido: {doc_type!r} (use um de {DOC_TYPES})")

    from integrations.ai import service as ai

    expected = holder_name or "(nome não informado)"
    schema = config.EXTRACT_SCHEMAS[doc_type]
    instruction = (
        "Você extrai dados de documentos escolares/oficiais brasileiros a partir de texto OCR. "
        "Responda APENAS o JSON pedido."
    )
    prompt = (
        f"Texto OCR de um documento do aluno ({doc_type}):\n\n{ocr_text}\n\n"
        f"O titular esperado desta conta é: {expected}.\n"
        "Compare o nome impresso no documento com o esperado: variações por CASAMENTO "
        "(sobrenome acrescentado, removido ou alterado) ou abreviações contam como 'sim', "
        "desde que seja claramente a MESMA pessoa; nome de OUTRA pessoa = 'nao'; nome "
        "ilegível ou ausente no texto = 'duvida'. Explique a comparação em name_reason. "
        "NÃO invente: qualquer campo que não estiver no texto = null."
    )
    try:
        data = ai.generate_json(
            prompt,
            caller=caller,
            instruction=instruction,
            schema_description=schema,
        )
    except Exception as exc:  # noqa: BLE001 — erro de IA na extração sobe
        logger.warning(
            "student_doc_ai.extract_failed", caller=caller, error=str(exc)[:200]
        )
        raise
    if not isinstance(data, dict):
        data = {}
    return data
