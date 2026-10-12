"""Comando de gerência para envio do Relatório Executivo (WhatsApp + TTS).

Uso:
    python manage.py send_executive_report
    python manage.py send_executive_report --phone 5543996648750
    python manage.py send_executive_report --hours 12
    python manage.py send_executive_report --dry-run
    python manage.py send_executive_report --no-tts
"""

from __future__ import annotations

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.reports.executive_report import (
    collect_analytics_metrics,
    format_whatsapp_message,
    format_tts_script,
    send_executive_report,
)


class Command(BaseCommand):
    help = "Gera e envia o Relatório Executivo de novidades (Leads, Pagamentos, Promotores) via WhatsApp com TTS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--phone",
            default=None,
            help="Telefone de destino no formato DDI+DDD+NUMERO (ex: 5543996648750). Default: admin do sistema.",
        )
        parser.add_argument(
            "--hours",
            type=float,
            default=None,
            help="Janela temporal em horas para análise (ex: 24, 12). Default: desde a última execução ou 24h.",
        )
        parser.add_argument(
            "--no-tts",
            action="store_true",
            help="Desativa a síntese e envio do áudio TTS, enviando apenas texto.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas exibe as métricas e o texto gerado no terminal, sem enviar ao WhatsApp.",
        )

    def handle(self, *args, **options):
        phone = options.get("phone")
        hours = options.get("hours")
        no_tts = options.get("no_tts")
        dry_run = options.get("dry_run")

        since = None
        if hours is not None:
            since = timezone.now() - timedelta(hours=hours)

        def safe_write(text: str, style_fn=None):
            out = style_fn(text) if style_fn else text
            try:
                self.stdout.write(out)
            except UnicodeEncodeError:
                self.stdout.write(out.encode("ascii", errors="replace").decode("ascii"))

        if dry_run:
            safe_write("[DRY-RUN] Modo Dry-Run ativo - nenhum envio sera realizado.", self.style.NOTICE)
            metrics = collect_analytics_metrics(since=since)
            msg = format_whatsapp_message(metrics)
            tts_script = format_tts_script(metrics)

            safe_write("\n" + "=" * 50)
            safe_write("[WHATSAPP] MENSAGEM WHATSAPP:", self.style.SUCCESS)
            safe_write("=" * 50)
            safe_write(msg)
            safe_write("\n" + "=" * 50)
            safe_write("[TTS] ROTEIRO DE AUDIO (TTS):", self.style.SUCCESS)
            safe_write("=" * 50)
            safe_write(tts_script)
            safe_write("=" * 50 + "\n")
            return

        safe_write("Gerando e enviando relatorio executivo...")
        result = send_executive_report(
            phone=phone,
            since=since,
            with_tts=not no_tts,
        )

        delivery = result.get("delivery", {})
        if delivery.get("text_delivered"):
            safe_write(f"[OK] Mensagem entregue no WhatsApp {result['phone']}!", self.style.SUCCESS)
        else:
            safe_write(f"[FALHA] Falha no envio de texto: {delivery.get('text_error')}", self.style.ERROR)

        if not no_tts:
            if delivery.get("audio_delivered"):
                safe_write(f"[OK] Audio TTS entregue no WhatsApp: {result.get('audio_url')}", self.style.SUCCESS)
            elif result.get("tts_error"):
                safe_write(f"[AVISO] Erro ao sintetizar TTS: {result.get('tts_error')}", self.style.WARNING)
            elif delivery.get("audio_error"):
                safe_write(f"[AVISO] Erro ao entregar audio: {delivery.get('audio_error')}", self.style.WARNING)
