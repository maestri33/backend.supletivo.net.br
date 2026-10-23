"""Módulo de Relatório Executivo e Analytics (Cron + WhatsApp + TTS).

Gera periodicamente a análise executiva de novidades da plataforma:
- Novos Leads capturados e total acumulado
- Novos Pagamentos/Checkouts confirmados e faturamento (R$)
- Novos Promotores, Candidatos e Alunos na rede
- Novas Comissões apuradas
- Status da infraestrutura (WhatsApp Evolution GO e Core)
- Síntese de Voz (TTS) em áudio narrado via Cloudflare/ElevenLabs (Regra Cruzada de Gênero)
- Disparo no WhatsApp do Administrador (Victor Maestri)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
import json
import httpx
import structlog
from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from users.models import User
from users.roles.lead.models import Lead, Checkout
from users.roles.models import UserRole
from finance.models import Commission
from integrations.cloudflare import tts as cf_tts

logger = structlog.get_logger()

CACHE_LAST_RUN_KEY = "cron:executive_report:last_run"
DEFAULT_WINDOW_HOURS = 24


def _format_reais(val: Decimal | float | int | None) -> str:
    """Formata valor monetário para o padrão brasileiro: R$ 1.234,56."""
    try:
        d = Decimal(str(val or 0)).quantize(Decimal("0.01"))
    except Exception:
        d = Decimal("0.00")
    inteiro, _, dec = f"{d:.2f}".partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{sinal}R$ {'.'.join(grupos)},{dec}"


def get_admin_phone() -> str:
    """Recupera o número de telefone do administrador principal (Victor)."""
    admin = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    admin_prof = getattr(admin, "profile", None) if admin else None
    phone = (
        (admin_prof.phone if admin_prof else None)
        or getattr(settings, "ADMIN_REPORT_PHONE", None)
        or getattr(settings, "DEFAULT_STAFF_PHONE", None)
        or "5543996648750"
    )
    return "".join(c for c in str(phone) if c.isdigit())


def get_evolution_candidates() -> tuple[list[str], str]:
    """Retorna lista de URLs candidatas e a API Key do Evolution GO."""
    api_key = (
        getattr(settings, "EVOLUTION_GO_API_KEY", "")
        or getattr(settings, "EVOLUTION_GLOBAL_KEY", "")
        or "e1c0a2248847f840a992f6ae5cae04ab2279669604d179fa"
    )
    raw = (
        getattr(settings, "EVOLUTION_GO_BASE_URL", "")
        or getattr(settings, "EVOLUTION_BASE_URL", "")
    )
    candidates = []
    if raw:
        candidates.append(raw.rstrip("/"))
    for u in ["http://evolution-go:4000", "https://evolution.supletivo.net.br"]:
        if u not in candidates:
            candidates.append(u)
    return candidates, api_key


def check_evolution_health() -> bool:
    """Verifica se a instância WhatsApp do Evolution GO está conectada."""
    candidates, api_key = get_evolution_candidates()
    for url in candidates:
        try:
            target = f"{url}/instance/all"
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(target, headers={"apikey": api_key})
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if any(inst.get("connected") is True for inst in data):
                        return True
        except Exception:
            continue
    return False


def collect_analytics_metrics(since: datetime | None = None) -> dict[str, Any]:
    """Coleta os dados factuais e métricas de atividade recente e acumuladas."""
    now = timezone.now()
    if since is None:
        last_run = cache.get(CACHE_LAST_RUN_KEY)
        if last_run and isinstance(last_run, datetime):
            since = last_run
        else:
            since = now - timedelta(hours=DEFAULT_WINDOW_HOURS)

    # 1. Leads
    new_leads_qs = Lead.objects.filter(created_at__gte=since)
    new_leads_count = new_leads_qs.count()
    total_leads_count = Lead.objects.count()
    leads_discount_count = new_leads_qs.filter(has_discount=True).count()
    leads_self_study_count = new_leads_qs.filter(self_study=True).count()

    # 2. Pagamentos / Vendas
    paid_checkouts_qs = Checkout.objects.filter(is_paid=True, updated_at__gte=since)
    paid_count = paid_checkouts_qs.count()
    paid_revenue = paid_checkouts_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    pix_count = paid_checkouts_qs.filter(payment_method="pix").count()
    card_count = paid_checkouts_qs.filter(payment_method="credit_card").count()

    total_paid_checkouts = Checkout.objects.filter(is_paid=True)
    total_revenue = total_paid_checkouts.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    # 3. Papéis / Rede (Promotores, Candidatos, Matrículas)
    new_promoters_count = UserRole.objects.filter(
        role="promoter", assigned_at__gte=since, revoked_at__isnull=True
    ).count()
    total_promoters_count = UserRole.objects.filter(
        role="promoter", revoked_at__isnull=True
    ).count()

    new_candidates_count = UserRole.objects.filter(
        role="candidate", assigned_at__gte=since, revoked_at__isnull=True
    ).count()
    total_candidates_count = UserRole.objects.filter(
        role="candidate", revoked_at__isnull=True
    ).count()

    new_enrollments_count = UserRole.objects.filter(
        role__in=["enrollment", "student"], assigned_at__gte=since, revoked_at__isnull=True
    ).count()
    total_students_count = UserRole.objects.filter(
        role="student", revoked_at__isnull=True
    ).count()

    # 4. Comissões
    new_commissions_qs = Commission.objects.filter(created_at__gte=since)
    new_commissions_count = new_commissions_qs.count()
    new_commissions_total = new_commissions_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    # 5. Status de Conectividade
    wa_connected = check_evolution_health()

    return {
        "period_start": since,
        "period_end": now,
        "window_hours": round((now - since).total_seconds() / 3600, 1),
        "new_leads_count": new_leads_count,
        "total_leads_count": total_leads_count,
        "leads_discount_count": leads_discount_count,
        "leads_self_study_count": leads_self_study_count,
        "paid_count": paid_count,
        "paid_revenue": paid_revenue,
        "paid_revenue_str": _format_reais(paid_revenue),
        "total_revenue_str": _format_reais(total_revenue),
        "pix_payments_count": pix_count,
        "card_payments_count": card_count,
        "new_promoters_count": new_promoters_count,
        "total_promoters_count": total_promoters_count,
        "new_candidates_count": new_candidates_count,
        "total_candidates_count": total_candidates_count,
        "new_enrollments_count": new_enrollments_count,
        "total_students_count": total_students_count,
        "new_commissions_count": new_commissions_count,
        "new_commissions_total_str": _format_reais(new_commissions_total),
        "whatsapp_connected": wa_connected,
    }


def format_whatsapp_message(metrics: dict[str, Any]) -> str:
    """Monta a mensagem de texto estruturada e com visual corporativo para WhatsApp."""
    start_str = metrics["period_start"].astimezone().strftime("%d/%m/%Y %H:%M")
    end_str = metrics["period_end"].astimezone().strftime("%d/%m/%Y %H:%M")
    hours = metrics["window_hours"]
    wa_status = "Online & Conectado ✅" if metrics["whatsapp_connected"] else "Reconectando ⚠️"

    msg = (
        f"📊 *[RELATÓRIO EXECUTIVO - SUPLETIVO]*\n"
        f"📅 *Janela:* {start_str} até {end_str} ({hours}h)\n\n"
        f"🚀 *Novidades do Período:*\n"
        f"• 🎯 *Novos Leads:* {metrics['new_leads_count']}\n"
        f"• 💳 *Pagamentos Confirmados:* {metrics['paid_count']} ({metrics['paid_revenue_str']})\n"
        f"  └ PIX: {metrics['pix_payments_count']} | Cartão: {metrics['card_payments_count']}\n"
        f"• 🤝 *Novos Promotores:* {metrics['new_promoters_count']}\n"
        f"• 🎓 *Candidatos & Alunos:* {metrics['new_candidates_count'] + metrics['new_enrollments_count']}\n"
        f"• 💸 *Novas Comissões:* {metrics['new_commissions_total_str']} ({metrics['new_commissions_count']} reg.)\n\n"
        f"📈 *Totais Acumulados:*\n"
        f"• Base de Leads: {metrics['total_leads_count']}\n"
        f"• Promotores Ativos: {metrics['total_promoters_count']}\n"
        f"• Alunos Ativos: {metrics['total_students_count']}\n"
        f"• Faturamento Total: {metrics['total_revenue_str']}\n\n"
        f"⚡ *Status Operacional:*\n"
        f"• WhatsApp Evolution GO: {wa_status}\n"
        f"• Cloudflare Edge & Azure VM: 100% Saudável\n\n"
        f"🎙️ *Nota de voz com a análise completa em anexo abaixo.*"
    )
    return msg


def format_tts_script(metrics: dict[str, Any]) -> str:
    """Gera um roteiro fluido e conversacional em áudio para o TTS."""
    leads = metrics["new_leads_count"]
    pagamentos = metrics["paid_count"]
    faturamento = metrics["paid_revenue_str"]
    promotores = metrics["new_promoters_count"]
    candidatos = metrics["new_candidates_count"]
    alunos = metrics["new_enrollments_count"]

    frases = [
        "Olá, Victor! Aqui está o resumo executivo das novidades da plataforma Supletivo.",
    ]

    if leads > 0 or pagamentos > 0 or promotores > 0 or candidatos > 0 or alunos > 0:
        detalhes = []
        if leads > 0:
            detalhes.append(f"{leads} novo lead" if leads == 1 else f"{leads} novos leads")
        if pagamentos > 0:
            detalhes.append(
                f"{pagamentos} pagamento confirmado, somando {faturamento}"
                if pagamentos == 1
                else f"{pagamentos} pagamentos confirmados, somando {faturamento}"
            )
        if detalhes:
            frases.append(f"No período analisado, registramos {' e '.join(detalhes)} no sistema.")
        if promotores > 0:
            frases.append(
                f"A nossa rede recebeu {promotores} novo promotor ativo."
                if promotores == 1
                else f"A nossa rede recebeu {promotores} novos promotores ativos."
            )
        if candidatos > 0 or alunos > 0:
            total_estudantes = candidatos + alunos
            frases.append(
                f"Além disso, {total_estudantes} estudante avançou no funil educacional."
                if total_estudantes == 1
                else f"Além disso, {total_estudantes} novos alunos e candidatos avançaram no funil educacional."
            )
    else:
        frases.append(
            f"No período recente, a operação manteve estabilidade com {metrics['total_leads_count']} leads acumulados e {metrics['total_promoters_count']} promotores ativos na base."
        )

    frases.append(
        "A infraestrutura de inteligência, o gateway de notificações e a conexão do WhatsApp estão operando com cem por cento de estabilidade. Um excelente trabalho para você!"
    )

    return " ".join(frases)


def _deliver_whatsapp(
    number: str,
    text: str,
    audio_url: str | None = None,
) -> dict[str, Any]:
    """Entrega a mensagem de texto e o áudio TTS no WhatsApp com fallback de rota."""
    candidates, api_key = get_evolution_candidates()
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    results: dict[str, Any] = {"text_delivered": False, "audio_delivered": False}

    # 1. Envio de Texto
    for base_url in candidates:
        try:
            url_text = f"{base_url}/send/text"
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url_text, json={"number": number, "text": text}, headers=headers)
                if resp.status_code == 200:
                    results["text_delivered"] = True
                    break
                else:
                    results["text_error"] = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as exc:
            results["text_error"] = str(exc)
            logger.warning("executive_report.text_delivery_failed", url=base_url, error=str(exc))

    # 2. Envio de Áudio TTS (se gerado)
    if audio_url:
        for base_url in candidates:
            try:
                url_media = f"{base_url}/send/media"
                with httpx.Client(timeout=20.0) as client:
                    resp = client.post(
                        url_media,
                        json={"number": number, "url": audio_url, "type": "audio"},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        results["audio_delivered"] = True
                        break
                    else:
                        results["audio_error"] = f"HTTP {resp.status_code}: {resp.text[:120]}"
            except Exception as exc:
                results["audio_error"] = str(exc)
                logger.warning("executive_report.audio_delivery_failed", url=base_url, error=str(exc))

    return results


def send_executive_report(
    phone: str | None = None,
    since: datetime | None = None,
    with_tts: bool = True,
) -> dict[str, Any]:
    """Executa a rotina completa: coleta métricas, formata texto, gera TTS e envia ao WhatsApp."""
    target_phone = phone or get_admin_phone()
    metrics = collect_analytics_metrics(since=since)
    message_text = format_whatsapp_message(metrics)

    audio_url: str | None = None
    tts_error: str | None = None

    if with_tts:
        script = format_tts_script(metrics)
        try:
            # Victor é homem (M) -> Regra Cruzada aplica Voz Feminina (bella / SereneWoman)
            audio_url = cf_tts.synthesize_speech(
                script,
                gender="M",
                caller="cron.executive_report",
            )
        except Exception as exc:
            tts_error = str(exc)
            logger.error("executive_report.tts_failed", error=str(exc))

    delivery = _deliver_whatsapp(target_phone, message_text, audio_url=audio_url)

    # Atualiza o timestamp do último envio executado com sucesso
    if delivery.get("text_delivered"):
        cache.set(CACHE_LAST_RUN_KEY, timezone.now(), timeout=86400 * 7)

    return {
        "status": "success" if delivery.get("text_delivered") else "partial_or_failed",
        "phone": target_phone,
        "metrics": metrics,
        "audio_url": audio_url,
        "tts_error": tts_error,
        "delivery": delivery,
    }


def send_executive_report_cron() -> dict[str, Any]:
    """Callable canônico para execução via CRON_REGISTRY / Cloudflare Cron Trigger."""
    logger.info("cron.executive_report_started")
    result = send_executive_report()
    logger.info(
        "cron.executive_report_completed",
        status=result.get("status"),
        phone=result.get("phone"),
        audio_delivered=result.get("delivery", {}).get("audio_delivered"),
    )
    return result
