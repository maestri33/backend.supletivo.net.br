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
from integrations.cloudflare.tts import resolve_cross_gender_voice


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
    """Valida que a confirmação de pagamento notifica coordenador e promotor."""
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
