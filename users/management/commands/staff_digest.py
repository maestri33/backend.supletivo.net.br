"""Digest operacional do staff — resumo financeiro do dia em 1 mensagem. MANUAL/AGENDADO.

Responde a pergunta que o staff mais faz: "como está o caixa / quanto vai sair?". Junta os agregados
que JÁ existem (CONVENTION §3): `finance.summary()` (comissões/payouts por status) +
`closing_obligation()` (quanto precisa sair na semana). Opcionalmente passa pela IA pra virar um
parágrafo legível (degrada pro texto cru se a IA estiver fora — nunca trava o digest).

Nasce **dry-run** (toca pessoa = mensagem): sem `--commit` só imprime. Com `--commit --to <id|phone>`
envia via notify (reusa `send_adhoc`). NÃO move dinheiro, NÃO muda estado — é leitura + texto.

Uso:
  python manage.py staff_digest                          # imprime o digest (factual)
  python manage.py staff_digest --ia                     # imprime com redação da IA
  python manage.py staff_digest --commit --to <external_id>   # envia ao staff (WhatsApp/e-mail)
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Digest financeiro do staff (dry-run por padrão; --commit --to envia)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="envia de verdade")
        parser.add_argument(
            "--to", default=None, help="external_id (ou telefone) do staff destinatário"
        )
        parser.add_argument(
            "--ia",
            action="store_true",
            help="passa o digest pela IA pra um texto mais legível (degrada pro cru se falhar)",
        )

    def handle(self, *args, **o):
        from finance import interface as finance_iface

        summary = finance_iface.summary()
        obligation = finance_iface.closing_obligation()
        text = _build_digest(summary, obligation, use_ia=o["ia"])

        if not o["commit"]:
            self.stdout.write(text)
            self.stdout.write("\n[dry-run] use --commit --to <id|phone> pra enviar.")
            return

        to = o["to"]
        if not to:
            raise CommandError("--commit exige --to <external_id|telefone> do staff.")
        from notify.interface.send import send_adhoc

        # heurística simples: só dígitos (>=10) = telefone livre; senão external_id de User.
        digits = "".join(c for c in to if c.isdigit())
        is_phone = len(digits) >= 10 and digits == to.strip().lstrip("+").replace(
            " ", ""
        )
        kwargs = {"phone": to} if is_phone else {"to_user": to}
        ext = send_adhoc(
            message=text,
            subject="Resumo financeiro — Supletivo Brasil",
            caller="staff.digest",
            **kwargs,
        )
        self.stdout.write(f"digest enviado (notification {ext}).")


def _money(v) -> str:
    """'1234.5' → 'R$ 1.234,50' (formato BR), tolerante a str/Decimal/None."""
    from decimal import Decimal, InvalidOperation

    try:
        d = Decimal(str(v or 0))
    except (InvalidOperation, TypeError, ValueError):
        return "R$ 0,00"
    inteiro, _, dec = f"{d:.2f}".partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{sinal}R$ {'.'.join(grupos)},{dec}"


def _build_digest(summary: dict, obligation: dict, *, use_ia: bool) -> str:
    """Monta o texto do digest a partir dos agregados. PURA (sem I/O além da IA opcional)."""
    comm = summary.get("commissions", {})
    pr = summary.get("payment_requests", {})

    def _line(bucket: dict, status: str, label: str) -> str | None:
        row = bucket.get(status)
        if not row or not row.get("count"):
            return None
        return f"  - {label}: {row['count']} ({_money(row.get('total'))})"

    parts = ["📊 Resumo financeiro — Supletivo Brasil\n", "Comissões:"]
    for st, lbl in [
        ("pending", "pendentes"),
        ("processed", "em processamento"),
        ("paid", "pagas"),
        ("failed", "falhas"),
    ]:
        line = _line(comm, st, lbl)
        if line:
            parts.append(line)

    parts.append("\nFila de pagamento:")
    for st, lbl in [
        ("queued", "na fila"),
        ("awaiting_pix", "aguardando chave PIX"),
        ("submitted", "enviados"),
        ("awaiting_balance", "aguardando saldo"),
        ("paid", "pagos"),
        ("failed", "falhas"),
    ]:
        line = _line(pr, st, lbl)
        if line:
            parts.append(line)

    parts.append(
        f"\nObrigação estimada da semana ({obligation.get('week_of', '?')}): "
        f"{_money(obligation.get('obrigacao_estimada'))}"
    )
    parts.append(
        f"  (comissões pendentes {_money(obligation.get('pending_commissions'))} + "
        f"fila ativa {_money(obligation.get('queued_payouts'))})"
    )
    raw = "\n".join(parts)

    if not use_ia:
        return raw
    try:
        from integrations.ai import service as ai

        return ai.summarize(
            raw,
            caller="staff.digest",
            format="paragraph",
        )
    except Exception:  # noqa: BLE001 — IA é enfeite: cai pro texto cru, nunca trava o digest
        return raw
