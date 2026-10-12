"""Testes automatizados do Relatório Executivo e Cron com WhatsApp e TTS."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.core.management import call_command
from django.utils import timezone
import pytest

from core.reports.executive_report import (
    collect_analytics_metrics,
    format_whatsapp_message,
    format_tts_script,
    send_executive_report,
    send_executive_report_cron,
)
from core.tasks import CRON_REGISTRY, run_cron_job


@pytest.mark.django_db
def test_cron_registry_contains_daily_executive_report():
    """Garante que daily_executive_report está devidamente registrado no CRON_REGISTRY."""
    assert "daily_executive_report" in CRON_REGISTRY
    entry = CRON_REGISTRY["daily_executive_report"]
    assert entry["func"] == "core.reports.executive_report.send_executive_report_cron"
    assert "Relatório executivo" in entry["description"]


@pytest.mark.django_db
def test_collect_analytics_metrics_returns_expected_structure():
    """Valida a coleta e cálculo das métricas de negócio."""
    metrics = collect_analytics_metrics()
    assert "new_leads_count" in metrics
    assert "total_leads_count" in metrics
    assert "paid_count" in metrics
    assert "paid_revenue_str" in metrics
    assert "new_promoters_count" in metrics
    assert "total_promoters_count" in metrics
    assert "whatsapp_connected" in metrics
    assert isinstance(metrics["new_leads_count"], int)
    assert isinstance(metrics["total_leads_count"], int)


@pytest.mark.django_db
def test_format_whatsapp_message_and_tts_script():
    """Valida formatação do texto e do roteiro para síntese de voz."""
    sample_metrics = {
        "period_start": timezone.now(),
        "period_end": timezone.now(),
        "window_hours": 24.0,
        "new_leads_count": 5,
        "total_leads_count": 12,
        "leads_discount_count": 3,
        "leads_self_study_count": 0,
        "paid_count": 2,
        "paid_revenue": Decimal("798.00"),
        "paid_revenue_str": "R$ 798,00",
        "total_revenue_str": "R$ 4.500,00",
        "pix_payments_count": 1,
        "card_payments_count": 1,
        "new_promoters_count": 2,
        "total_promoters_count": 8,
        "new_candidates_count": 1,
        "total_candidates_count": 4,
        "new_enrollments_count": 1,
        "total_students_count": 3,
        "new_commissions_count": 2,
        "new_commissions_total_str": "R$ 200,00",
        "whatsapp_connected": True,
    }

    msg = format_whatsapp_message(sample_metrics)
    assert "RELATÓRIO EXECUTIVO" in msg
    assert "Novos Leads:* 5" in msg
    assert "R$ 798,00" in msg
    assert "Novos Promotores:* 2" in msg
    assert "Online & Conectado" in msg

    tts_script = format_tts_script(sample_metrics)
    assert "Olá, Victor!" in tts_script
    assert "5 novos leads" in tts_script
    assert "R$ 798,00" in tts_script
    assert "2 novos promotores" in tts_script


@pytest.mark.django_db
@patch("core.reports.executive_report._deliver_whatsapp")
@patch("core.reports.executive_report.cf_tts.synthesize_speech")
def test_send_executive_report_flow(mock_tts, mock_deliver):
    """Testa o fluxo completo de envio com TTS e entrega mockada."""
    mock_tts.return_value = "https://r2.dev/test.mp3"
    mock_deliver.return_value = {"text_delivered": True, "audio_delivered": True}

    res = send_executive_report(phone="5543996648750", with_tts=True)
    assert res["status"] == "success"
    assert res["phone"] == "5543996648750"
    assert res["audio_url"] == "https://r2.dev/test.mp3"
    assert res["delivery"]["text_delivered"] is True
    assert res["delivery"]["audio_delivered"] is True

    mock_tts.assert_called_once()
    mock_deliver.assert_called_once()


@pytest.mark.django_db
@patch("core.reports.executive_report.send_executive_report")
def test_run_cron_job_daily_executive_report(mock_report):
    """Testa execução através do executor global run_cron_job."""
    mock_report.return_value = {"status": "success", "phone": "5543996648750"}
    res = run_cron_job("daily_executive_report")
    assert res["status"] == "success"
    assert res["job"] == "daily_executive_report"
    assert res["result"]["status"] == "success"


@pytest.mark.django_db
def test_management_command_dry_run(capsys):
    """Testa o comando de gerência em modo dry-run."""
    call_command("send_executive_report", "--dry-run")
    captured = capsys.readouterr()
    assert "Modo Dry-Run ativo" in captured.out
    assert "MENSAGEM WHATSAPP" in captured.out
    assert "ROTEIRO DE AUDIO" in captured.out or "ROTEIRO DE ÁUDIO" in captured.out
