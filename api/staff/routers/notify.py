"""Router de Notificações, Templates, TTS, Mídias e Histórico (Staff)."""

from __future__ import annotations

from typing import Any
import httpx
import structlog
from django.conf import settings
from ninja import Router

from api.auth import require_superuser
from api.staff.schemas import (
    AiAssistIn,
    AiAssistOut,
    NotifyEventOut,
    NotifyHistoryItemOut,
    NotifyPreviewOut,
    NotifyTemplateOut,
    NotifyTemplateStatsOut,
    NotifyTestOut,
    PreviewIn,
    TemplatePatchIn,
    TestIn,
    TtsConfigOut,
    TtsProbeIn,
    TtsProbeOut,
)
from users.exceptions import NotFound, ValidationError

logger = structlog.get_logger()
router = Router(tags=["staff"])

# Catálogo completo e categorizado de eventos de notificação do V7M
DEFAULT_EVENTS_CATALOG = [
    # ── Autenticação & Segurança ──
    {"event": "auth.otp", "label": "Autenticação: Código OTP WhatsApp", "category": "auth"},
    {"event": "auth.cpf_conflict", "label": "Segurança: Alerta de conflito de CPF", "category": "auth"},

    # ── Captação de Leads & Checkout ──
    {"event": "lead.captured", "label": "Lead: Inscrição iniciada no formulário", "category": "lead"},
    {"event": "lead.captured.promoter", "label": "Lead: Aviso ao promotor sobre novo lead", "category": "lead"},
    {"event": "lead.captured.coordinator", "label": "Lead: Aviso ao coordenador sobre novo lead", "category": "lead"},
    {"event": "lead.checkout.pix", "label": "Lead: Link de pagamento PIX gerado", "category": "lead"},
    {"event": "lead.checkout.card", "label": "Lead: Link de pagamento Cartão gerado", "category": "lead"},
    {"event": "lead.paid", "label": "Lead: Pagamento confirmado (Boas-vindas)", "category": "lead"},
    {"event": "lead.paid.receipt", "label": "Lead: Comprovante de pagamento emitido", "category": "lead"},
    {"event": "lead.paid.promoter", "label": "Lead: Matrícula paga (Comissão gerada)", "category": "lead"},
    {"event": "lead.paid.promoter.scholarship", "label": "Lead: Matrícula paga (Meta da bolsa)", "category": "lead"},
    {"event": "lead.paid.coordinator", "label": "Lead: Notificação de pagamento ao polo", "category": "lead"},
    {"event": "lead.payment_reminder", "label": "Lead: Lembrete de pagamento pendente", "category": "lead"},

    # ── Matrícula & Documentos ──
    {"event": "enrollment.welcome", "label": "Matrícula: Boas-vindas e início da jornada", "category": "enrollment"},
    {"event": "enrollment.credentials", "label": "Matrícula: Envio de login e senha EAD", "category": "enrollment"},
    {"event": "enrollment.fee_due", "label": "Matrícula: Cobrança de taxa gerada", "category": "enrollment"},
    {"event": "enrollment.fee_paid", "label": "Matrícula: Taxa de matrícula confirmada", "category": "enrollment"},
    {"event": "enrollment.fee_due_paid", "label": "Matrícula: Taxa em atraso quitada", "category": "enrollment"},
    {"event": "enrollment.fee_scheduled", "label": "Matrícula: Taxa de matrícula agendada", "category": "enrollment"},
    {"event": "enrollment.fee_problem", "label": "Matrícula: Falha no pagamento da taxa", "category": "enrollment"},
    {"event": "enrollment.rg_in_review", "label": "Matrícula: RG em análise", "category": "enrollment"},
    {"event": "enrollment.rg_approved", "label": "Matrícula: RG aprovado com sucesso", "category": "enrollment"},
    {"event": "enrollment.rg_rejected", "label": "Matrícula: RG rejeitado (solicitar reenvio)", "category": "enrollment"},
    {"event": "enrollment.selfie_in_review", "label": "Matrícula: Selfie em análise biométrica", "category": "enrollment"},
    {"event": "enrollment.selfie_approved", "label": "Matrícula: Selfie aprovada", "category": "enrollment"},
    {"event": "enrollment.selfie_rejected", "label": "Matrícula: Selfie biométrica rejeitada", "category": "enrollment"},
    {"event": "enrollment.address_proof_rejected", "label": "Matrícula: Comprovante de endereço rejeitado", "category": "enrollment"},
    {"event": "enrollment.awaiting_release", "label": "Matrícula: Aguardando liberação de acesso", "category": "enrollment"},
    {"event": "enrollment.released", "label": "Matrícula: Acesso liberado no sistema", "category": "enrollment"},
    {"event": "enrollment.concluded_referral", "label": "Matrícula: Indicação concluiu e virou aluno", "category": "enrollment"},

    # ── Candidatos a Promotores ──
    {"event": "candidate.awaiting_approval", "label": "Candidato: Cadastro aguardando aprovação", "category": "candidate"},
    {"event": "candidate.doc_type_reset", "label": "Candidato: Reenvio de documento liberado", "category": "candidate"},
    {"event": "candidate.document_in_review", "label": "Candidato: Documento em análise", "category": "candidate"},
    {"event": "candidate.document_approved", "label": "Candidato: Documento aprovado", "category": "candidate"},
    {"event": "candidate.document_rejected", "label": "Candidato: Documento rejeitado", "category": "candidate"},
    {"event": "candidate.selfie_in_review", "label": "Candidato: Selfie em análise", "category": "candidate"},
    {"event": "candidate.selfie_approved", "label": "Candidato: Selfie aprovada", "category": "candidate"},
    {"event": "candidate.selfie_rejected", "label": "Candidato: Selfie rejeitada", "category": "candidate"},
    {"event": "candidate.rejected", "label": "Candidato: Candidatura recusada", "category": "candidate"},

    # ── Treinamento & Promotores ──
    {"event": "training.unlocked", "label": "Treinamento: Módulo de estudos liberado", "category": "training"},
    {"event": "training.must_train", "label": "Treinamento: Convocação para treinamento", "category": "training"},
    {"event": "training.must_train.scholarship", "label": "Treinamento: Início de trilha da bolsa", "category": "training"},
    {"event": "training.new_material", "label": "Treinamento: Novo material disponível", "category": "training"},
    {"event": "training.cleared", "label": "Treinamento: Promotor aprovado no curso", "category": "training"},
    {"event": "training.approved", "label": "Treinamento: Conclusão aprovada", "category": "training"},
    {"event": "training.approved.scholarship", "label": "Treinamento: Bolsa ativada com sucesso", "category": "training"},
    {"event": "training.submission_rejected", "label": "Treinamento: Atividade enviada rejeitada", "category": "training"},
    {"event": "promoter.lead_invite", "label": "Promotor: Convite enviado para contato", "category": "promoter"},
    {"event": "promoter.new_lead", "label": "Promotor: Novo lead indicado", "category": "promoter"},
    {"event": "promoter.lead_paid", "label": "Promotor: Comissão gerada por indicação", "category": "promoter"},
    {"event": "promoter.suspended", "label": "Promotor: Conta suspensa temporariamente", "category": "promoter"},
    {"event": "promoter.reactivated", "label": "Promotor: Conta reativada", "category": "promoter"},
    {"event": "promoter.weekly_closing", "label": "Promotor: Fechamento semanal de comissões", "category": "promoter"},

    # ── Alunos & Provas ──
    {"event": "student.exam_scheduled", "label": "Aluno: Prova final agendada", "category": "student"},
    {"event": "student.exam_released", "label": "Aluno: Prova final liberada", "category": "student"},
    {"event": "student.exam_passed", "label": "Aluno: Aprovado na prova final", "category": "student"},
    {"event": "student.exam_failed", "label": "Aluno: Reprovado na prova final", "category": "student"},
    {"event": "student.document_in_review", "label": "Aluno: Documentação final em análise", "category": "student"},
    {"event": "student.document_rejected", "label": "Aluno: Documentação final rejeitada", "category": "student"},
    {"event": "student.diploma_issued", "label": "Aluno: Diploma / Certificado emitido", "category": "student"},
    {"event": "student.diploma_pickup", "label": "Aluno: Diploma pronto para retirada no polo", "category": "student"},
    {"event": "student.pendency_opened", "label": "Aluno: Pendência acadêmica aberta", "category": "student"},
    {"event": "student.veteran", "label": "Aluno: Transição para aluno veterano", "category": "student"},
    {"event": "student.veteran.coordinator", "label": "Aluno: Aluno veterano ativo no polo", "category": "student"},

    # ── Financeiro & Polos ──
    {"event": "finance.commission_paid", "label": "Financeiro: Comissão paga via PIX", "category": "finance"},
    {"event": "hub.coordinator_assigned", "label": "Polo: Coordenador atribuído ao polo", "category": "hub"},
]

DEFAULT_TEMPLATES = {
    "auth.otp": {
        "title": "Código de verificação",
        "subject": "Seu código de acesso Supletivo Brasil",
        "body_md": "Olá! Seu código de verificação é: *{codigo}*\n\nEste código expira em *{ttl_minutos}* minutos.\n\nSe você não solicitou este acesso, ignore esta mensagem.",
        "channels": "whatsapp",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "supletivo",
        "notes": "Envia o código numérico de 6 dígitos no login/registro passwordless",
    },
    "auth.cpf_conflict": {
        "title": "Alerta de segurança",
        "subject": "Tentativa de uso do seu CPF no Supletivo Brasil",
        "body_md": "🔒 Alguém tentou usar o seu CPF para criar um cadastro no Supletivo Brasil em {data} às {hora}, com o número {numero}. O cadastro foi bloqueado e desfeito automaticamente. Se não foi você, fale com o nosso suporte por este WhatsApp.",
        "channels": "whatsapp,email",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "supletivo",
        "notes": "Avisa o titular legítimo de uma tentativa de cadastro com seu CPF",
    },
    "finance.commission_paid": {
        "title": "Comissão paga",
        "subject": "Sua comissão foi paga! 💸",
        "body_md": "Olá, {nome}! Sua comissão foi paga. 💸\n\nAcabamos de enviar o PIX de R$ {valor} referente ao fechamento da sua semana. O valor deve cair na sua conta em instantes.",
        "channels": "whatsapp,email",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "v7m",
        "notes": "Notifica o promotor quando o PIX semanal de comissão é confirmado",
    },
    "lead.captured": {
        "title": "Inscrição Iniciada",
        "subject": "Sua matrícula no Supletivo",
        "body_md": "Olá, {nome}! Recebemos sua inscrição no Supletivo V7M. Para concluir, acesse seu link de pagamento: {link}",
        "channels": "whatsapp,email",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "default",
        "notes": "Disparado assim que o lead preenche o formulário",
    },
    "lead.paid": {
        "title": "Matrícula Confirmada!",
        "subject": "Parabéns! Sua matrícula foi confirmada",
        "body_md": "Parabéns, {nome}! Seu pagamento foi confirmado com sucesso. Em breve você receberá seu acesso à plataforma de estudos.",
        "channels": "whatsapp,email",
        "is_tts": True,
        "media_url": None,
        "media_type": None,
        "mail_template": "default",
        "notes": "Disparado após webhook de pagamento confirmado",
    },
    "lead.payment_reminder": {
        "title": "Sua matrícula está quase lá",
        "subject": "Lembrete de pagamento da sua matrícula",
        "body_md": "Olá, {nome}! Passando pra lembrar que a sua matrícula no Supletivo Brasil ainda está aguardando o pagamento. 😊\n\nÉ rapidinho, pelo link: {payment_link}\n\nSe já pagou, pode ignorar esta mensagem — a confirmação é automática. Qualquer dúvida, é só responder aqui que um atendente te ajuda.",
        "channels": "whatsapp,email",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "supletivo",
        "notes": "Lembrete diário enviado para leads com pagamento pendente",
    },
    "enrollment.credentials": {
        "title": "Seu Acesso à Plataforma",
        "subject": "Credenciais de Acesso ao Supletivo",
        "body_md": "Olá {nome}! Seus dados de acesso à plataforma de estudos são:\n\n*Login:* {login}\n*Senha:* {senha}\n*Acesse em:* {url}",
        "channels": "whatsapp,email",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "credentials",
        "notes": "Envia o login/senha gerados para o aluno",
    },
    "promoter.lead_paid": {
        "title": "Nova Comissão Gerada!",
        "subject": "Você ganhou uma nova comissão!",
        "body_md": "Show de bola, {nome}! Sua indicação {aluno_nome} acabou de se matricular. Você acumulou +R$ {valor} de comissão!",
        "channels": "whatsapp",
        "is_tts": True,
        "media_url": None,
        "media_type": None,
        "mail_template": "default",
        "notes": "Notifica o promotor quando seu lead paga",
    },
    "promoter.lead_invite": {
        "title": "Convite Supletivo Brasil",
        "subject": "Você recebeu um convite para conhecer o Supletivo",
        "body_md": "Você recebeu um convite para conhecer o Supletivo V7M.\n\nAcesse com segurança pelo link: {link}\n\nVocê confirma seus próprios dados antes de qualquer matrícula.",
        "channels": "whatsapp",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "supletivo",
        "notes": "Mensagem enviada no convite direto de promotor",
    },
    "enrollment.concluded_referral": {
        "title": "Nova matrícula concluída por indicação!",
        "subject": "Sua indicação concluiu a matrícula! 🎓",
        "body_md": "Parabéns, {nome}! Sua indicação concluiu a matrícula e virou aluno com sucesso! 🎓",
        "channels": "whatsapp,email",
        "is_tts": False,
        "media_url": None,
        "media_type": None,
        "mail_template": "v7m",
        "notes": "Notifica o promotor quando o lead indicado vira aluno",
    },
}


def _notify_server_request(method: str, path: str, json: dict | None = None, params: dict | None = None) -> Any:
    """Encaminha requisição para a API administrativa do notify-server."""
    server_url = getattr(settings, "NOTIFY_SERVER_URL", "http://notify-web:8000")
    api_key = getattr(settings, "NOTIFY_API_KEY", "")
    timeout = getattr(settings, "NOTIFY_TIMEOUT", 10.0)

    try:
        with httpx.Client(
            base_url=server_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        ) as client:
            resp = client.request(method, path, json=json, params=params)
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                logger.warning("notify.proxy_error", status=resp.status_code, body=resp.text)
                return None
            return resp.json()
    except Exception as exc:
        logger.warning("notify.server_unreachable", error=str(exc))
        return None


def _trigger_out(tr) -> dict | None:
    if tr is None:
        return None
    return {
        "fires_on": tr.fires_on or "",
        "source": tr.source or None,
        "delay_minutes": tr.delay_minutes,
        "active": tr.active,
    }


def _template_to_out(t) -> dict:
    tr = getattr(t, "trigger", None)
    return {
        "event": t.event,
        "external_id": str(t.external_id),
        "title": t.title,
        "subject": t.subject,
        "body_md": t.body_md,
        "is_tts": t.is_tts,
        "channels": t.channels,
        "media_url": t.media_url,
        "media_type": t.media_type,
        "mail_template": t.mail_template,
        "notes": t.notes,
        "updated_at": t.updated_at.isoformat() if hasattr(t.updated_at, "isoformat") else str(t.updated_at),
        "trigger": _trigger_out(tr),
    }


@router.get("/notify/templates", response=list[NotifyTemplateOut], summary="Listagem de todos os templates de notificação")
def list_templates(request):
    """Lista todos os templates cadastrados no banco do backend."""
    require_superuser(request.auth)
    from notify.models import Template
    templates = Template.objects.select_related("trigger").all().order_by("event")
    return [_template_to_out(t) for t in templates]


@router.get("/notify/templates/stats", response=NotifyTemplateStatsOut, summary="Estatísticas agregadas de templates")
def template_stats(request):
    """Retorna contadores de templates ativos, com TTS, com IA e por canal."""
    require_superuser(request.auth)
    from notify.models import Template
    templates = list(Template.objects.select_related("trigger").all())
    total = len(templates)
    active = sum(1 for t in templates if getattr(t, "trigger", None) and t.trigger.active)
    inactive = total - active
    with_tts = sum(1 for t in templates if t.is_tts)
    with_media = sum(1 for t in templates if t.media_url)
    by_channel = {
        "whatsapp": sum(1 for t in templates if "whatsapp" in t.channels),
        "email": sum(1 for t in templates if "email" in t.channels),
    }

    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "with_tts": with_tts,
        "with_media": with_media,
        "by_channel": by_channel,
    }


@router.get("/notify/events", response=list[NotifyEventOut], summary="Listagem de todos os eventos suportados")
def list_events(request):
    """Lista todos os eventos cadastrados no banco do backend."""
    require_superuser(request.auth)
    from notify.models import Template

    events_in_db = set(Template.objects.values_list("event", flat=True))
    catalog_map = {ev["event"]: ev for ev in DEFAULT_EVENTS_CATALOG}
    all_keys = list(catalog_map.keys())
    for ev in sorted(events_in_db):
        if ev not in catalog_map:
            all_keys.append(ev)

    return [
        {
            "event": k,
            "has_template": k in events_in_db,
            "has_in_memory": k in DEFAULT_TEMPLATES,
            "active": True,
        }
        for k in all_keys
    ]


@router.post("/notify/templates/ai-assist", response=AiAssistOut, summary="Assistência de IA para edição de mensagem")
def ai_assist(request, payload: AiAssistIn):
    """Reescreve e otimiza o texto do template preservando estritamente variáveis de contexto."""
    require_superuser(request.auth)
    from integrations.ai import service as ai_service

    text = (payload.text or "").strip()
    if not text:
        return {"text": "", "action": payload.action}

    action_instructions = {
        "improve": "Melhore a clareza, o tom acolhedor e a naturalidade desta mensagem de notificação para WhatsApp/E-mail.",
        "simplify": "Simplifique a linguagem tornando a mensagem direta, fácil de entender e sem jargões.",
        "shorten": "Encurte a mensagem mantendo apenas a informação essencial e o call to action.",
        "fix": "Corrija qualquer erro gramatical, ortográfico ou de pontuação em português brasileiro.",
        "persuade": "Torne a mensagem mais persuasiva, motivadora e incentivadora para o destinatário tomar a ação necessária.",
    }

    instruction = action_instructions.get(payload.action, action_instructions["improve"])
    if payload.action == "custom" and payload.custom_prompt:
        instruction = f"Instrução do administrador: {payload.custom_prompt.strip()}"

    system_prompt = (
        f"{instruction} "
        "REGRAS OBRIGATÓRIAS: "
        "1. PRESERVE ESTRITAMENTE todas as variáveis entre chaves no texto original, exatamente como escritas "
        "(ex.: {nome}, {codigo}, {link}, {payment_link}, {valor}, {ttl_minutos}, etc.). NUNCA remova, altere ou invente variáveis. "
        "2. Responda SEMPRE em português brasileiro natural e profissional. "
        "3. Devolva APENAS o texto da mensagem final pronto para uso. SEM introduções, SEM aspas ao redor, SEM comentários ou explicações."
    )

    try:
        refined = ai_service.complete_text(
            prompt=text,
            system_prompt=system_prompt,
            caller="staff.notify.ai_assist",
            temperature=0.3,
            max_tokens=600,
        )
        clean_text = refined.strip().strip('"').strip("'")
        return {"text": clean_text, "action": payload.action}
    except Exception as exc:
        logger.warning("notify.ai_assist_error", error=str(exc))
        return {"text": text, "action": payload.action}


@router.get("/notify/templates/{event}", response=NotifyTemplateOut, summary="Obter detalhes de template")
def get_template(request, event: str):
    """Retorna os dados completos do template do banco local."""
    require_superuser(request.auth)
    from notify.models import Template
    tpl = Template.objects.select_related("trigger").filter(event=event).first()
    if tpl is None:
        raise NotFound(f"Template '{event}' não encontrado.", code="TEMPLATE_NOT_FOUND")
    return _template_to_out(tpl)


@router.patch("/notify/templates/{event}", response=NotifyTemplateOut, summary="Atualizar template de notificação")
def patch_template(request, event: str, payload: TemplatePatchIn):
    """Edita os campos de texto, TTS, mídia e canais do template diretamente no banco local."""
    require_superuser(request.auth)
    from notify.models import Template, Trigger
    from notify.interface.templates import invalidate

    data = payload.dict(exclude_unset=True)
    tpl = Template.objects.select_related("trigger").filter(event=event).first()
    if tpl is None:
        tpl = Template.objects.create(event=event, body_md=data.get("body_md", ""))
        Trigger.objects.create(template=tpl, fires_on=event)

    for k, v in data.items():
        if hasattr(tpl, k):
            setattr(tpl, k, v)
    tpl.save()
    invalidate(event)
    return _template_to_out(tpl)


@router.post("/notify/templates/{event}/restore-seed", response=NotifyTemplateOut, summary="Restaurar template do seed")
def restore_seed(request, event: str):
    """Sobrescreve o template no banco do backend com a versão padrão do seed."""
    require_superuser(request.auth)
    from pathlib import Path
    from notify.models import Template, Trigger
    from notify.seed import io as seed_io
    from notify.interface.templates import invalidate

    file_path = Path(__file__).resolve().parents[4] / "notify" / "seed" / "templates.md"
    if not file_path.exists():
        file_path = Path(__file__).resolve().parents[3] / "notify" / "seed" / "templates.md"

    if file_path.exists():
        specs = seed_io.parse(file_path.read_text(encoding="utf-8"))
        spec = next((s for s in specs if s.event == event), None)
        if spec:
            tpl, _ = Template.objects.get_or_create(event=event)
            tpl.title = spec.title
            tpl.subject = spec.subject
            tpl.body_md = spec.body_md
            tpl.is_tts = getattr(spec, "is_tts", False)
            tpl.channels = spec.channels
            tpl.media_url = spec.media_url
            tpl.media_type = spec.media_type
            tpl.mail_template = spec.mail_template
            tpl.save()
            tr, _ = Trigger.objects.get_or_create(template=tpl)
            tr.fires_on = spec.fires_on or ""
            tr.source = spec.source
            tr.delay_minutes = spec.delay_minutes
            tr.active = spec.active
            tr.save()
            invalidate(event)
            return _template_to_out(tpl)

    tpl = Template.objects.select_related("trigger").filter(event=event).first()
    if tpl is None:
        raise NotFound(f"Template {event} não encontrado.", code="TEMPLATE_NOT_FOUND")
    return _template_to_out(tpl)


@router.post("/notify/templates/{event}/preview", response=NotifyPreviewOut, summary="Visualizar prévia renderizada")
def preview_template(request, event: str, payload: PreviewIn):
    """Renderiza a prévia do texto substituindo as variáveis dinâmicas de contexto localmente."""
    require_superuser(request.auth)
    from notify.models import Template
    from notify.interface.templates import render

    tpl = Template.objects.filter(event=event).first()
    body_md = tpl.body_md if tpl else f"Template {event}"
    is_tts = tpl.is_tts if tpl else False
    channels = tpl.channel_list if tpl else ["whatsapp", "email"]

    ctx = {
        "nome": "Victor",
        "nome_completo": "Victor Maestri",
        "name": "Victor",
        "link": "https://v7m.org/matricula/xyz",
        "payment_link": "https://v7m.org/pagar/xyz",
        "valor": "150,00",
        "codigo": "849201",
        "ttl_minutos": "10",
        "data": "26/08/2026",
        "hora": "10:30",
        "numero": "(42) 9****-1770",
        "login": "victor.aluno",
        "senha": "v7m" + str(1234),
        "url": "https://ead.supletivobrasil.com.br",
        "aluno_nome": "João da Silva",
        "student_external_id": "std_98234",
        "material_title": "Matemática Financeira Básica",
        "justification": "Arquivo ilegível ou foto cortada",
        "enroll_goal": "3",
        "exam_goal": "5",
        "detail": "Documento cortado nas bordas",
    }
    if payload.ctx:
        ctx.update(payload.ctx)

    rendered = render(body_md, ctx)
    return {
        "event": event,
        "body_md": body_md,
        "rendered": rendered,
        "is_tts": is_tts,
        "channels": list(channels),
    }


@router.post("/notify/templates/{event}/test", response=NotifyTestOut, summary="Enviar notificação de teste")
def test_template(request, event: str, payload: TestIn):
    """Dispara um envio real de teste para o Staff logado nos canais configurados."""
    require_superuser(request.auth)
    from users.profiles.models import Profile
    from notify.interface.events import send_event

    principal = request.auth
    profile = Profile.objects.filter(user__external_id=principal.external_id).first()
    if not profile or not profile.phone:
        raise ValidationError("Staff logado não possui telefone cadastrado no perfil para teste.", code="NO_PHONE")

    ext_id = send_event(
        event=event,
        phone=profile.phone,
        email=profile.email,
        ctx=payload.ctx or {"nome": profile.name or "Staff"},
        run_sync=True,
    )
    return {"external_id": ext_id or "test-dispatched"}


@router.get("/notify/history", response=list[NotifyHistoryItemOut], summary="Histórico de notificações enviadas")
def notify_history(request, limit: int = 100):
    """Consulta o histórico de disparos com status por canal (WhatsApp, E-mail, TTS)."""
    require_superuser(request.auth)
    from notify.sdk import client as notify_client

    try:
        remote = notify_client.get_notifications(limit=limit)
        if isinstance(remote, list):
            return remote
    except Exception as exc:
        logger.warning("notify.history_error", error=str(exc))

    return []


@router.get("/notify/tts/config", response=TtsConfigOut, summary="Configuração de TTS e Cadeia de Provedores")
def tts_config(request):
    """Retorna a URL base do OmniRoute, a cadeia de fallback e a regra de gênero cruzado."""
    require_superuser(request.auth)
    from integrations.ai.tts import _get_omniroute_base_url, get_tts_chain

    chain_opts = get_tts_chain()
    return {
        "omniroute_url": _get_omniroute_base_url(),
        "chain": [
            {
                "model": opt.model,
                "voice_female": opt.voice_female,
                "voice_male": opt.voice_male,
            }
            for opt in chain_opts
        ],
        "cross_gender_rule": "Destinatário Homem (M) recebe voz feminina; Mulher (F) recebe voz masculina.",
    }


@router.post("/notify/tts/probe", response=TtsProbeOut, summary="Testar síntese de voz (TTS) em tempo real")
def tts_probe(request, payload: TtsProbeIn):
    """Sintetiza um áudio de teste no OmniRoute e devolve a URL pública do áudio para preview."""
    require_superuser(request.auth)
    from integrations.ai.tts import (
        _get_omniroute_base_url,
        get_tts_chain,
        probe_tts,
        synthesize_voice_note,
    )

    audio_url = synthesize_voice_note(
        payload.text,
        gender=payload.gender,
        voice_override=payload.voice_override,
        caller="admin.probe",
    )

    probe_diag = probe_tts(text=payload.text, gender=payload.gender)
    chain = get_tts_chain()
    first_opt = chain[0]
    used_voice = payload.voice_override or first_opt.voice_for(payload.gender)

    return {
        "ok": bool(audio_url),
        "audio_url": audio_url,
        "gender_target": payload.gender or "default",
        "voice_used": used_voice,
        "omniroute_url": _get_omniroute_base_url(),
        "chain_results": probe_diag.get("chain_results", []),
    }


