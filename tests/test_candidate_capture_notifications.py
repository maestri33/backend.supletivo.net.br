from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock
import pytest

from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.profiles.models import Profile
from users.roles.candidate.models import Candidate
from users.roles.candidate import capture
from integrations.cloudflare.tts import clean_text_for_speech


@pytest.mark.django_db
def test_candidate_capture_triggers_both_notifications():
    """Valida o disparo simétrico de notificações na captura de candidato:
    - candidate.captured com áudio TTS (is_tts_override=True) para o candidato.
    - candidate.captured.coordinator com dados completos, wa.me e link do painel para o coordenador.
    """
    coord_user = User.objects.create_user(external_id=uuid.uuid4())
    coord_profile = Profile.objects.create(
        user=coord_user,
        name="Victor Coordenador",
        phone="5543996648750",
        gender="M",
    )
    hub = Hub.objects.create(
        address=Address.objects.create(city="Ponta Grossa", state="PR"),
        brand="standard",
        coordinator=coord_user,
        is_default=True,
    )

    cand_user = User.objects.create_user(external_id=uuid.uuid4())
    cand_profile = Profile.objects.create(
        user=cand_user,
        name="Diandra Candidata",
        phone="554298171770",
        cpf="07461638947",
        gender="F",
    )

    with patch("notify.interface.events.send_event") as mock_send_event:
        candidate = Candidate.objects.create(
            user=cand_user,
            hub=hub,
            status=Candidate.Status.STARTED,
        )
        capture._notify_candidate_captured(candidate)
        capture._notify_coordinator_new_candidate(candidate)

        assert mock_send_event.call_count == 2

        # 1. Notificação do candidato (com áudio TTS)
        cand_call = mock_send_event.call_args_list[0]
        assert cand_call.args[0] == "candidate.captured"
        assert cand_call.kwargs["profile"] == cand_profile
        assert cand_call.kwargs["gender"] == "F"
        assert cand_call.kwargs["is_tts_override"] is True
        assert cand_call.kwargs["ctx"]["candidato_nome"] == "Diandra Candidata"
        assert cand_call.kwargs["ctx"]["polo_nome"] == "Central"  # normalizado sem prefixo duplicado
        assert "colaborador" in cand_call.kwargs["ctx"]["link_app"]
        assert cand_call.kwargs["idempotency_key"] == f"candidate_captured_{candidate.external_id}"

        # 2. Notificação do coordenador (ficha com WhatsApp)
        coord_call = mock_send_event.call_args_list[1]
        assert coord_call.args[0] == "candidate.captured.coordinator"
        assert coord_call.kwargs["profile"] == coord_profile
        assert coord_call.kwargs["gender"] == "M"
        assert coord_call.kwargs["ctx"]["candidato_nome"] == "Diandra Candidata"
        assert coord_call.kwargs["ctx"]["candidato_telefone"] == "(42) 9817-1770"
        assert coord_call.kwargs["ctx"]["candidato_whatsapp_url"] == "https://wa.me/554298171770"
        assert coord_call.kwargs["ctx"]["polo_nome"] == "Central"
        assert "admin" in coord_call.kwargs["ctx"]["link_painel"]
        assert coord_call.kwargs["idempotency_key"] == f"candidate_captured_coord_{candidate.external_id}"


@pytest.mark.django_db
def test_candidate_capture_without_coordinator_resilient():
    """Garante que a ausência de coordenador no polo não quebra a captura nem o disparo pro candidato."""
    hub_no_coord = Hub.objects.create(
        address=Address.objects.create(city="Curitiba", state="PR"),
        brand="Polo Sem Coordenador",
        coordinator=None,
        is_default=False,
    )

    cand_user = User.objects.create_user(external_id=uuid.uuid4())
    cand_profile = Profile.objects.create(
        user=cand_user,
        name="Candidato Sem Coord",
        phone="5542999999999",
        gender="M",
    )

    with patch("notify.interface.events.send_event") as mock_send_event:
        candidate = Candidate.objects.create(
            user=cand_user,
            hub=hub_no_coord,
            status=Candidate.Status.STARTED,
        )
        capture._notify_candidate_captured(candidate)
        capture._notify_coordinator_new_candidate(candidate)

        # Apenas 1 chamada (para o candidato)
        assert mock_send_event.call_count == 1
        assert mock_send_event.call_args[0][0] == "candidate.captured"


@pytest.mark.django_db
def test_candidate_captured_audio_tts_sanitization():
    """Valida que o texto do template candidate.captured é higienizado pelo clean_text_for_speech
    removendo links Markdown / URLs cruas para evitar leitura indecifrável no sintetizador.
    """
    sample_text = (
        "Olá, Diandra! Ficamos muito felizes com a sua decisão de fazer parte da nossa equipe no polo Polo Central.\n\n"
        "Você deu o primeiro passo para se tornar um promotor oficial do Supletivo Brasil e transformar a sua história.\n\n"
        "Conclua o seu cadastro pelo aplicativo para liberar o seu acesso completo:\n"
        "https://app.supletivo.net.br/colaborador"
    )
    cleaned = clean_text_for_speech(sample_text)
    assert "https://" not in cleaned
    assert "app.supletivo.net.br" not in cleaned
    assert "Olá, Diandra!" in cleaned


@pytest.mark.django_db
def test_check_or_capture_calls_notifications_via_interface():
    """Valida a integração fim-a-fim de check_or_capture disparando ambas as notificações."""
    coord_user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(
        user=coord_user,
        name="Victor Coord",
        phone="5543996648750",
        gender="M",
    )
    Hub.objects.create(
        address=Address.objects.create(city="Ponta Grossa", state="PR"),
        brand="standard",
        coordinator=coord_user,
        is_default=True,
    )

    with patch("users.roles.candidate.capture.auth_iface.check") as mock_check, \
         patch("users.roles.candidate.capture.auth_iface.register") as mock_reg, \
         patch("notify.interface.events.send_event") as mock_send_event:

        cand_ext_id = uuid.uuid4()
        cand_user = User.objects.create_user(external_id=cand_ext_id)
        Profile.objects.create(
            user=cand_user,
            name="Diandra",
            phone="554298171770",
            gender="F",
        )

        mock_check.return_value = {
            "found": False,
            "whatsapp": True,
        }
        mock_reg.return_value = {
            "external_id": str(cand_ext_id),
            "otp_sent": True,
        }

        res = capture.check_or_capture(
            phone="554298171770",
            cpf="07461638947",
            send_otp=True,
            hub="standard",
        )

        assert res["created"] is True
        assert mock_send_event.call_count == 2
        calls = [c.args[0] for c in mock_send_event.call_args_list]
        assert "candidate.captured" in calls
        assert "candidate.captured.coordinator" in calls
