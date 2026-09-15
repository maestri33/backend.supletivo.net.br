"""Registry mínimo de hooks in-process (CONVENTION §7.3).

O webhook de um app de `integrations/` valida o evento, mexe só no próprio estado e então
**dispara o hook do app destino** — sem importar o app consumidor (desacoplado). Aqui mora a
engrenagem: o consumidor (ex.: `users/roles/lead`) registra um handler por NOME de evento no boot
(AppConfig.ready()); o webhook chama `dispatch(evento, **kw)`.

Quando ninguém consome, o webhook mantém o payload bruto e registra um warning estruturado.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

logger = structlog.get_logger()

_HOOKS: dict[str, list[Callable]] = {}


def register(event: str, handler: Callable) -> None:
    """Registra um handler para um evento (idempotente: não duplica o mesmo handler)."""
    handlers = _HOOKS.setdefault(event, [])
    if handler not in handlers:
        handlers.append(handler)


def dispatch(event: str, *, reraise: bool = False, **kwargs) -> bool:
    """Chama os handlers do evento. Retorna True se ALGUM consumiu (handler retornou truthy).

    Exceção de handler é sempre logada. `reraise=False` (default): NÃO propaga — um consumidor com
    bug não derruba o caller. `reraise=True` (G4): PROPAGA — o webhook de pagamento PRECISA disso:
    se o efeito de negócio (comissão/matrícula) falhou, a view deve dar não-2xx pro gateway
    re-tentar, em vez de mascarar como sucesso (200) e nunca reprocessar. O retry é seguro porque os
    handlers são idempotentes (lead.status==PAID → no-op).
    """
    consumed = False
    for handler in _HOOKS.get(event, ()):
        try:
            if handler(**kwargs):
                consumed = True
        except Exception as exc:  # noqa: BLE001 — isola o caller de bug do consumidor
            logger.error(
                "hook_failed",
                hook_event=event,  # 'event' colide com o posicional do structlog
                handler=getattr(handler, "__name__", repr(handler)),
                error=str(exc),
            )
            if reraise:
                raise
    return consumed
