"""System check do app finance — avisa (não trava) quando a config de comissão está quebrada.

finance é app interno de apoio (não tem credencial externa que justifique travar o boot). Aqui só
Warnings: valor de comissão <= 0 ou threshold <= 0 quase certamente é `.env` mal preenchido.

- `finance.W001` (Warning): algum valor de comissão (direct/bonus/coordinator) <= 0.
- `finance.W002` (Warning): COMMISSION_BONUS_THRESHOLD <= 0.
"""

from django.core.checks import Warning as DjangoWarning

from finance import config


def check_finance_config(app_configs, **kwargs):
    warnings = []
    amounts = {
        "COMMISSION_DIRECT": config.direct_amount(),
        "COMMISSION_BONUS_FLAT": config.bonus_amount(),
        "COMMISSION_COORDINATOR": config.coordinator_amount(),
    }
    zeradas = [name for name, value in amounts.items() if value <= 0]
    if zeradas:
        warnings.append(
            DjangoWarning(
                f"Valor(es) de comissão <= 0: {', '.join(zeradas)} — config provável errada.",
                hint="Defina os valores (em reais) em backend/.env. DEV mini = 1/5/1.",
                id="finance.W001",
            )
        )
    if config.bonus_threshold() <= 0:
        warnings.append(
            DjangoWarning(
                "COMMISSION_BONUS_THRESHOLD <= 0 — o bônus dispararia sempre.",
                hint="Defina COMMISSION_BONUS_THRESHOLD (contagem de indicações/semana, ex.: 5).",
                id="finance.W002",
            )
        )
    return warnings
