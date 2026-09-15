"""Lembrete de pagamento aos leads PENDING — disparo MANUAL/AGENDADO, nunca no deploy.

Filosofia (Victor 2026-06-30): isto TOCA o cliente (mensagem de cobrança), então nasce **dry-run**:
sem `--commit` ele só LISTA quem seria avisado (auditável antes de mandar). Com `--commit`, dispara
pelo notify reusando o link curto JÁ gerado — não toca no gateway, não muda status, não inventa nada.

Cadência = 1 lembrete por lead por dia: garantida pela `idempotency_key` do notify
(`payment_reminder:<lead>:<AAAA-MM-DD>`) — re-rodar no mesmo dia é no-op. Pra agendar (ex.: Django-Q
schedule 1x/dia), aponte pra este command com `--commit`; o intervalo é decisão operacional do Victor,
não ligo nada sozinho.

(Vive em `users/` — não em `users/roles/lead/` — porque só `users` é app instalado; o Django só
descobre commands de apps no INSTALLED_APPS. A regra de elegibilidade mora em `lead/reminders.py`.)

Uso:
  python manage.py payment_reminder                      # dry-run: lista os elegíveis
  python manage.py payment_reminder --commit             # dispara (1/dia por idempotência)
  python manage.py payment_reminder --min-age 24 --max-age 168 --commit
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.roles.lead import reminders


class Command(BaseCommand):
    help = "Lembra leads com pagamento pendente (dry-run por padrão; --commit dispara)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="dispara de verdade (sem isto é dry-run: só lista)",
        )
        parser.add_argument(
            "--min-age",
            type=int,
            default=24,
            help="idade mínima do lead em horas pra ser lembrado (default 24)",
        )
        parser.add_argument(
            "--max-age",
            type=int,
            default=168,
            help="idade máxima em horas (default 168 = 7 dias; não persegue lead morto)",
        )

    def handle(self, *args, **o):
        targets = reminders.due_reminders(
            min_age_hours=o["min_age"], max_age_hours=o["max_age"]
        )
        if not targets:
            self.stdout.write("nenhum lead elegível a lembrete na janela.")
            return

        if not o["commit"]:
            self.stdout.write(f"[DRY-RUN] {len(targets)} lead(s) seriam lembrados:")
            for t in targets:
                self.stdout.write(
                    f"  - {t.lead_external_id}  ({t.age_hours}h)  tel={_mask(t.phone)}"
                )
            self.stdout.write("\nrode com --commit pra disparar.")
            return

        today = timezone.localdate().isoformat()
        sent = 0
        from notify.interface.events import send_event

        for t in targets:
            send_event(
                "lead.payment_reminder",
                phone=t.phone,
                gender=t.gender,
                ctx={
                    "nome": t.name or "Futuro Aluno",
                    "payment_link": t.payment_link,
                },
                idempotency_key=f"payment_reminder:{t.lead_external_id}:{today}",
            )
            sent += 1
        self.stdout.write(f"disparados {sent} lembrete(s) (idempotente por dia).")


def _mask(phone: str) -> str:
    """Mascara o telefone no log do dry-run (não vaza PII inteira)."""
    return phone[:4] + "***" + phone[-2:] if len(phone) > 6 else "***"
