"""Config do finance — lida 1× de `settings` (CONVENTION §10: um .env, nada de os.getenv espalhado).

Valores em **REAIS (Decimal, 2 casas)**, igual ao asaas — NUNCA float (só o infinitepay usa centavos).
DEV mini (teste mexe DINHEIRO REAL): comissão 1 / bônus 5 / coord 1 / threshold 5. PROD pede ao Victor
(ref 100/500/50). O parse vem de string pra não passar por float.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings


from core.system_config import get_setting


def _money(name: str, default: str) -> Decimal:
    # str() antes do Decimal: se vier float do settings, ainda assim não herda erro binário.
    val = get_setting(name, getattr(settings, name, default))
    return Decimal(str(val))


def direct_amount() -> Decimal:
    """Comissão direta por lead que PAGOU (pro promotor que indicou)."""
    return _money("COMMISSION_DIRECT", "1")


def bonus_amount() -> Decimal:
    """Bônus FLAT do promotor com >= threshold indicações na semana (não escala)."""
    return _money("COMMISSION_BONUS_FLAT", "200")


def coordinator_amount() -> Decimal:
    """Comissão flat por student→veteran (R$ 50,00 pro promotor/coordenador do hub)."""
    return _money("COMMISSION_COORDINATOR", "50")


def bonus_threshold() -> int:
    """Quantas indicações na semana destravam o bônus (contagem, não valor)."""
    return int(get_setting("COMMISSION_BONUS_THRESHOLD", getattr(settings, "COMMISSION_BONUS_THRESHOLD", 3)))


def closing_weekday() -> int:
    """Dia do fechamento: 0=segunda .. 4=sexta (default sexta)."""
    return int(get_setting("COMMISSION_CLOSING_WEEKDAY", getattr(settings, "COMMISSION_CLOSING_WEEKDAY", 4)))


def closing_hour() -> int:
    """Hora do fechamento em America/Sao_Paulo (default 18h)."""
    return int(get_setting("COMMISSION_CLOSING_HOUR", getattr(settings, "COMMISSION_CLOSING_HOUR", 18)))

