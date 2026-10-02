"""Testes automatizados do fluxo de notificações com áudio TTS para Promotores e Coordenadores.

Diretivas:
- Promotor que entra recebe evento com áudio TTS (is_tts: true).
- Coordenador do polo que recebe matrícula paga recebe evento lead.paid.coordinator com áudio TTS (is_tts: true).
- Promotor que indicou o lead recebe lead.paid.promoter com áudio TTS (is_tts: true).
- Regra Cruzada de Gênero:
    * Destinatário Masculino (M) -> Voz Feminina (bella no ElevenLabs Turbo v2.5)
    * Destinatário Feminino (F) -> Voz Masculina (antoni no ElevenLabs Turbo v2.5)
"""

import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.utils import timezone

from users.models import User, Profile, Promoter, Lead, Checkout, LeadAttribution, Address
from hub.models import Hub
from notify.models import Template
from users.roles.lead.service import _notify_paid
from users.roles.candidate.promotion import _promote_to_promoter
from users.roles.candidate.models import Candidate
from integrations.cloudflare.tts import resolve_cross_gender_voice, clean_text_for_speech
from notify.interface import templates as tpl_iface
from finance.interface import commissions as fin_commissions
from finance.models import Commission, PaymentRequest
from finance import config as fin_config
import uuid


@pytest.mark.django_db
def test_cross_gender_voice_resolution():
    """Valida a regra cruzada canônica de vozes do ElevenLabs Turbo v2.5."""
    male_voice = resolve_cross_gender_voice("M")
    assert male_voice["eleven_model"] == "elevenlabs/eleven_turbo_v2_5"
    assert male_voice["eleven_voice"] == "bella"  # Homem recebe voz feminina

    female_voice = resolve_cross_gender_voice("F")
    assert female_voice["eleven_model"] == "elevenlabs/eleven_turbo_v2_5"
    assert female_voice["eleven_voice"] == "antoni"  # Mulher recebe voz masculina

    default_voice = resolve_cross_gender_voice(None)
    assert default_voice["eleven_voice"] == "antoni"


@pytest.mark.django_db
def test_templates_have_audio_tts_enabled():
    """Garante que os templates críticos possuem is_tts=True configurado."""
    critical_events = [
        "training.approved",
        "training.must_train",
        "lead.paid.coordinator",
        "lead.paid.promoter",
    ]
    for ev in critical_events:
        tpl, _ = Template.objects.get_or_create(
            event=ev,
            defaults={"title": ev, "body_md": "Olá {name}", "is_tts": True},
        )
        assert tpl.is_tts is True, f"Template {ev} deve ter is_tts=True"


@pytest.mark.django_db
@patch("notify.interface.events.send_event")
def test_candidate_promotion_notifies_with_audio_tts(mock_send):
    """Valida que a promoção do candidato a promotor dispara notificação."""
    user = User.objects.create_user()
    Profile.objects.create(
        user=user,
        phone="554298171770",
        name="Diandra Adelmaris",
        gender="F",
    )
    addr = Address.objects.create(
        street="Rua Teste", number="10", neighborhood="Centro", city="Ponta Grossa", state="PR", zipcode="84000000"
    )
    hub = Hub.objects.create(address=addr, brand="standard")
    from users.roles import interface as roles
    roles.assign(user, "candidate")
    cand = Candidate.objects.create(user=user, hub=hub, status="started")

    locked = _promote_to_promoter(cand)

    assert mock_send.called
    call_args = mock_send.call_args[0]
    event_dispatched = call_args[0]
    assert event_dispatched in ("training.approved", "training.must_train")
    assert Promoter.objects.filter(user=user).exists()


@pytest.mark.django_db
@patch("notify.interface.events.send_event")
def test_paid_lead_notifies_coordinator_and_promoter_with_audio(mock_send):
    """Valida que a confirmação de pagamento notifica coordenador e promotor com contexto completo."""
    coord_user = User.objects.create_user()
    Profile.objects.create(
        user=coord_user,
        phone="5543996648750",
        name="Victor Coordenador",
        gender="M",
    )
    addr = Address.objects.create(
        street="Rua Hub", number="20", neighborhood="Centro", city="Londrina", state="PR", zipcode="86000000"
    )
    hub = Hub.objects.create(address=addr, brand="standard", coordinator=coord_user)

    promoter_user = User.objects.create_user()
    Profile.objects.create(
        user=promoter_user,
        phone="554298171770",
        name="Diandra Promotora",
        gender="F",
    )
    Promoter.objects.create(user=promoter_user, hub=hub)

    lead_user = User.objects.create_user()
    Profile.objects.create(
        user=lead_user,
        phone="5511999991111",
        name="Aluno Matriculado",
        gender="M",
    )
    lead = Lead.objects.create(
        user=lead_user,
        promoter=promoter_user,
        status=Lead.Status.PENDING,
    )
    checkout = Checkout.objects.create(
        lead=lead,
        payment_method=Checkout.Method.PIX,
        provider=Checkout.Provider.ASAAS,
        amount=Decimal("999.00"),
        is_paid=True,
    )

    _notify_paid(lead, hub, checkout)

    # Verifica os eventos disparados
    events_called = [c[0][0] for c in mock_send.call_args_list]
    assert "lead.paid" in events_called
    assert "lead.paid.coordinator" in events_called
    assert "lead.paid.promoter" in events_called

    calls_by_event = {c[0][0]: c[1] for c in mock_send.call_args_list}

    # Validação do evento do coordenador
    coord_call = calls_by_event["lead.paid.coordinator"]
    assert coord_call.get("gender") == "M"
    coord_ctx = coord_call.get("ctx", {})
    assert coord_ctx.get("link_painel") == "https://admin.supletivo.net.br/coordenador"
    assert coord_ctx.get("aluno_nome") == "Aluno Matriculado"
    assert coord_ctx.get("aluno_telefone") == "(11) 99999-1111"
    assert coord_ctx.get("polo_nome") == "Polo Central"

    # Validação do evento do promotor
    prom_call = calls_by_event["lead.paid.promoter"]
    assert prom_call.get("gender") == "F"
    prom_ctx = prom_call.get("ctx", {})
    assert prom_ctx.get("aluno_nome") == "Aluno Matriculado"
    assert prom_ctx.get("aluno_telefone") == "(11) 99999-1111"
    assert "wa.me/5511999991111" in prom_ctx.get("aluno_whatsapp_url", "")
    assert prom_ctx.get("comissao_direta") == f"R${fin_config.direct_amount()}"
    assert prom_ctx.get("meta_bonus") == str(fin_config.bonus_threshold())
    assert "leads_semana" in prom_ctx
    assert "falta_para_bonus" in prom_ctx


def test_clean_text_for_speech_strips_urls_and_special_chars():
    """Valida que URLs, emojis, bullets e variáveis cruas são expurgados do áudio."""
    raw = (
        "Olá *Victor*! ✅ Uma nova matrícula entrou no polo Polo Londrina! • (43) 99999-1111\n"
        "Acompanhe o acolhimento pedagógico e o envio de documentos pelo painel:\n"
        "https://admin.supletivo.net.br/coordenador"
    )
    cleaned = clean_text_for_speech(raw)
    assert "https://" not in cleaned
    assert "admin.supletivo" not in cleaned
    assert "•" not in cleaned
    assert "✅" not in cleaned
    assert "*" not in cleaned
    assert "Acompanhe o acolhimento pedagógico e o envio de documentos pelo painel." in cleaned

    # Garante que placeholders não interpolados nunca são lidos
    raw_with_var = "Acesse o painel: {link_painel}"
    cleaned_var = clean_text_for_speech(raw_with_var)
    assert "{link_painel}" not in cleaned_var
    assert "{" not in cleaned_var
    assert "}" not in cleaned_var


@pytest.mark.django_db
def test_template_rendering_and_speech_never_leaks_raw_variables():
    """Garante que a renderização dos templates de coordinator e promoter com o contexto de _notify_paid
    nunca deixa {link_painel} ou outras variáveis cruas no texto final e áudio."""
    coord_tpl = tpl_iface.get("lead.paid.coordinator")
    assert coord_tpl is not None

    ctx_coord = {
        "aluno_nome": "João Silva",
        "aluno_telefone": "(41) 98888-7777",
        "polo_nome": "Polo Curitiba",
        "link_painel": "https://admin.supletivo.net.br/coordenador",
    }
    rendered_coord = tpl_iface.render(coord_tpl.body_md, ctx_coord)
    assert "{link_painel}" not in rendered_coord
    assert "https://admin.supletivo.net.br/coordenador" in rendered_coord

    spoken_coord = clean_text_for_speech(rendered_coord)
    assert "https://" not in spoken_coord
    assert "admin.supletivo" not in spoken_coord
    assert "{link_painel}" not in spoken_coord

    prom_tpl = tpl_iface.get("lead.paid.promoter")
    assert prom_tpl is not None
    ctx_prom = {
        "aluno_nome": "João Silva",
        "aluno_telefone": "(41) 98888-7777",
        "aluno_whatsapp_url": "https://wa.me/5541988887777",
        "comissao_direta": "R$100",
        "leads_semana": "1",
        "meta_bonus": "5",
        "falta_para_bonus": "4",
    }
    rendered_prom = tpl_iface.render(prom_tpl.body_md, ctx_prom)
    assert "{aluno_nome}" not in rendered_prom
    assert "{comissao_direta}" not in rendered_prom
    assert "{leads_semana}" not in rendered_prom
    assert "{meta_bonus}" not in rendered_prom
    assert "{falta_para_bonus}" not in rendered_prom

    spoken_prom = clean_text_for_speech(rendered_prom)
    assert "https://" not in spoken_prom
    assert "wa.me" not in spoken_prom
    assert "✅" not in spoken_prom
    assert "💸" not in spoken_prom


@pytest.mark.django_db
def test_promoter_with_20_leads_gets_20_commissions_and_exactly_one_flat_bonus():
    """Regra de bônus no fechamento semanal:
    Se o promotor fizer 20 matrículas, ganha 20 comissões diretas e EXATAMENTE 1 bônus flat de meta na semana
    (não duplica nem multiplica).
    """
    promoter = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(
        user=promoter,
        phone="554298171770",
        name="Promotor Vinte",
        pix_key="4298171770",
        pix_key_type="phone",
        gender="M",
    )

    direct_amount = fin_config.direct_amount()
    bonus_amount = fin_config.bonus_amount()

    # Cria 20 comissões diretas de lead para o promotor
    for _ in range(20):
        lead_id = uuid.uuid4()
        c = fin_commissions.credit_commission(
            payee=promoter,
            payee_role=Commission.Role.PROMOTER,
            source_type=Commission.Source.LEAD,
            source_external_id=lead_id,
        )
        assert c.status == Commission.Status.PENDING

    direct_comms = Commission.objects.filter(
        payee=promoter, source_type=Commission.Source.LEAD
    )
    assert direct_comms.count() == 20

    # Executa fechamento semanal
    fin_commissions.run_weekly_closing()

    # Confirma: EXATAMENTE 1 bônus flat de meta gerado
    bonus_comms = Commission.objects.filter(
        payee=promoter, source_type=Commission.Source.BONUS
    )
    assert bonus_comms.count() == 1, "Promotor deve receber EXATAMENTE 1 bônus flat, sem multiplicar!"
    bonus = bonus_comms.first()
    assert bonus.amount == bonus_amount
    assert bonus.status == Commission.Status.PROCESSED

    # Todas as 20 comissões diretas agora estão processadas
    assert direct_comms.filter(status=Commission.Status.PROCESSED).count() == 20

    # Confirma que o PaymentRequest consolidou 21 itens (20 diretas + 1 bônus)
    req = PaymentRequest.objects.filter(payee=promoter).first()
    assert req is not None
    assert req.commissions.count() == 21
    expected_total = (20 * direct_amount) + bonus_amount
    assert req.amount == expected_total

    # Re-executar fechamento semanal é idempotente (não gera segundo bônus nem duplica request)
    fin_commissions.run_weekly_closing()
    assert Commission.objects.filter(payee=promoter, source_type=Commission.Source.BONUS).count() == 1
    assert PaymentRequest.objects.filter(payee=promoter).count() == 1

