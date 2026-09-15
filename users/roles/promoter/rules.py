"""Regras da BOLSA do promotor — folha do grafo de imports (só lê `lead.models`).

Mora fora do `promoter/service.py` porque o `student/service.py` precisa do gate de prova
(`BOLSA_EXAM_THRESHOLD`) e o `service` do promotor importa `enrollment`, que importa `student`:
o import fechava ciclo. A regra não depende de nenhum service — é uma contagem — então vira folha
e os dois lados a importam sem se enxergar.
"""

from __future__ import annotations

from django.conf import settings
from core.system_config import get_setting

# Gates da bolsa (Victor): 3 indicações pagas auto-matriculam o promotor pré-matriculado;
# 10 liberam a prova do bolsista (soma com docs+sangue, não substitui).
BOLSA_ENROLL_THRESHOLD = 3
BOLSA_EXAM_THRESHOLD = 10


def get_bolsa_enroll_threshold() -> int:
    """Nº de alunos captados para liberar a auto-matrícula do promotor."""
    return int(
        get_setting(
            "PROMOTER_STUDY_UNLOCK_THRESHOLD",
            getattr(settings, "PROMOTER_STUDY_UNLOCK_THRESHOLD", BOLSA_ENROLL_THRESHOLD),
        )
    )


def get_bolsa_exam_threshold() -> int:
    """Nº de alunos captados para quitar o curso / liberar a prova final."""
    return int(
        get_setting(
            "PROMOTER_STUDY_COMPLETE_THRESHOLD",
            getattr(settings, "PROMOTER_STUDY_COMPLETE_THRESHOLD", BOLSA_EXAM_THRESHOLD),
        )
    )


def paid_referrals(user) -> int:
    """Nº de leads PAGOS captados pelo promotor (self_study fora) — a definição canônica de
    'indicação' (espelha `summary().lifetime.total_students`). Usado nos gates da bolsa."""
    from users.roles.lead.models import Lead

    return Lead.objects.filter(
        promoter=user, status=Lead.Status.PAID, self_study=False
    ).count()
