"""System checks do core — hoje só observabilidade (Sentry).

Padrão do repo (ver `notify/checks.py`): `W*` avisa, `E*` trava o boot. Sentry é APOIO — um deploy
sem DSN funciona igual, só fica cego — então `sentry.W001` é Warning e não derruba nada. Config
QUEBRADA (sample-rate fora da faixa, `SENTRY_REQUEST_BODY` inválido) trava, mas isso já acontece
antes daqui: o `init_sentry` levanta `ImproperlyConfigured` durante o import do settings.
"""

from django.conf import settings
from django.core.checks import Warning as DjangoWarning


def check_sentry(app_configs, **kwargs):
    warnings = []

    if getattr(settings, "APP_ENV", "") == "prod" and not getattr(
        settings, "SENTRY_DSN", ""
    ):
        warnings.append(
            DjangoWarning(
                "APP_ENV=prod sem SENTRY_DSN — o backend sobe, mas exceção em produção "
                "morre no log JSON do host (ninguém é avisado).",
                hint="Defina SENTRY_DSN em backend/.env. Sem projeto Sentry ainda? "
                "Um DSN de GlitchTip self-hosted serve — o SDK é o mesmo.",
                id="sentry.W001",
            )
        )

    # `send_default_pii=False` é hardcoded no core/sentry.py, mas o CORPO do request é opção
    # separada do SDK (o gate de PII não cobre o corpo). "always"/"medium" em prod = cpf, telefone
    # e chave Pix do funil viajando pro painel. A denylist ainda mascara o que casa por chave, mas
    # não é onde a gente quer estar apoiado. §LGPD.
    if getattr(settings, "APP_ENV", "") == "prod" and getattr(
        settings, "SENTRY_REQUEST_BODY", "never"
    ) not in ("never", "small"):
        warnings.append(
            DjangoWarning(
                f"SENTRY_REQUEST_BODY={settings.SENTRY_REQUEST_BODY!r} em prod — o corpo dos "
                "POSTs do funil (cpf/telefone/pix) passa a ser anexado aos eventos.",
                hint="Use SENTRY_REQUEST_BODY=never em prod; afrouxe só em dev/staging.",
                id="sentry.W002",
            )
        )

    return warnings
