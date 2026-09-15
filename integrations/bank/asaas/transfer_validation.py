"""Mecanismo de Validação de Saque do Asaas (doc oficial:
https://docs.asaas.com/docs/mecanismo-para-validacao-de-saque-via-webhooks).

Habilitado, o Asaas chama POST ~5s após CADA saída (TRANSFER, PIX_QR_CODE, BILL,
MOBILE_PHONE_RECHARGE, PIX_REFUND) pedindo autorização. Respondemos:
  {"status": "APPROVED"}                                   -> Asaas executa
  {"status": "REFUSED", "refuseReason": "<motivo>"}        -> Asaas cancela
3 falhas (ou resposta que não seja APPROVED/REFUSED) -> Asaas cancela a operação.

Aprova SÓ saída que NÓS iniciamos e que bate com o nosso DB. Como payout (1a-v) ainda não cria
nenhum Payment de saída, hoje RECUSA tudo — lado seguro do dinheiro (CONVENTION §8).
"""

import structlog

from .models import Payment

logger = structlog.get_logger()

# Tipos que o app inicia -> kind do Payment correspondente.
_TYPE_TO_KIND = {
    "TRANSFER": Payment.Kind.PIXKEY,
    "PIX_QR_CODE": Payment.Kind.QRCODE,
    "BILL": Payment.Kind.BOLETO,  # boleto avulso (billpay.pay_bill) — também iniciado por nós.
}
# Tipos que NÃO iniciamos -> recusa categórica.
_UNSUPPORTED_TYPES = {"MOBILE_PHONE_RECHARGE", "PIX_REFUND"}
# Status do Payment aceitos pra autorizar (entre o claim local e o webhook de conclusão).
_VALIDATABLE_STATUSES = ("SUBMITTING", "SUBMITTED")
# Campo do payload onde o Asaas aninha os dados da operação, por type.
_PAYLOAD_FIELD = {
    "TRANSFER": "transfer",
    "PIX_QR_CODE": "pixQrCode",
    "BILL": "bill",
}


def validate(payload):
    """Retorna (approved: bool, refuse_reason: str | None). approved=True implica reason=None."""
    if not isinstance(payload, dict):
        return False, "invalid_payload"
    op_type = payload.get("type")
    if not op_type or not isinstance(op_type, str):
        return False, "missing_type"
    if op_type in _UNSUPPORTED_TYPES:
        return False, f"unsupported_operation_type: {op_type}"
    kind = _TYPE_TO_KIND.get(op_type)
    if kind is None:
        return False, f"unknown_type: {op_type}"

    # Campo do payload segue o type: transfer.id / pixQrCode.id / bill.id.
    payload_field = _PAYLOAD_FIELD.get(op_type, op_type.lower())
    op = payload.get(payload_field)
    if not isinstance(op, dict):
        return False, f"missing_{payload_field}_object"
    asaas_id = op.get("id")
    if not asaas_id:
        return False, "missing_id_in_payload"

    row = Payment.objects.filter(
        asaas_id=asaas_id, kind=kind, status__in=_VALIDATABLE_STATUSES
    ).first()
    if row is None:
        return False, f"operation_not_found_locally: id={asaas_id}"

    asaas_value = op.get("value")
    if asaas_value is not None:
        local = round(float(row.amount), 2)
        remote = round(float(asaas_value), 2)
        if local != remote:
            return False, f"value_mismatch: local={local} remote={remote}"
    return True, None


def decide(payload):
    """Body de resposta pro Asaas (APPROVED/REFUSED) + log de auditoria da decisão."""
    approved, refuse_reason = validate(payload)
    op_type = payload.get("type") if isinstance(payload, dict) else None
    op_id = None
    if isinstance(payload, dict):
        op = (
            payload.get("transfer")
            or payload.get("pixQrCode")
            or payload.get("bill")
            or {}
        )
        if isinstance(op, dict):
            op_id = op.get("id")
    logger.info(
        "transfer_validation_decision",
        approved=approved,
        refuse_reason=refuse_reason,
        op_type=op_type,
        op_id=op_id,
    )
    if approved:
        return {"status": "APPROVED"}
    return {"status": "REFUSED", "refuseReason": refuse_reason or "unknown"}
