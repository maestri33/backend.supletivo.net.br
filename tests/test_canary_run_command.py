"""Testes para o management command canary_run."""
from datetime import timedelta
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from core.models import PlatformSetting
from finance import canary
from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.profiles.models import Profile
from users.roles.promoter.models import Promoter

pytestmark = pytest.mark.django_db


def test_canary_run_command_full_cycle(capsys):
    actor = User.objects.create_user(is_staff=True)
    Profile.objects.create(user=actor, cpf="00011122233", phone="5541999990001")

    owner = User.objects.create_user()
    Profile.objects.create(user=owner, cpf="11144477735", phone="554399611111", pix_key="11144477735")
    hub = Hub.objects.create(address=Address.objects.create(city="Curitiba", state="PR"), brand="standard")
    Promoter.objects.create(user=owner, hub=hub, activated_at=timezone.now() - timedelta(days=21))

    # 1. Status inicial (sem canário)
    call_command("canary_run", "status", skip_checks=True)
    captured = capsys.readouterr()
    assert "Nenhum canário configurado" in captured.out

    # 2. Configure via command
    call_command(
        "canary_run",
        "configure",
        actor_cpf="00011122233",
        owner_cpf="11144477735",
        student_cpf="52998224725",
        student_phone="42998222222",
        ttl=12,
        justification="Teste automatizado de homologação",
        skip_checks=True,
    )
    captured = capsys.readouterr()
    assert "Canário configurado com sucesso!" in captured.out

    # 3. Status após configure
    call_command("canary_run", "status", skip_checks=True)
    captured = capsys.readouterr()
    assert "ATIVO" in captured.out
    assert "0 / 5" in captured.out

    # 4. Disable via command
    call_command(
        "canary_run",
        "disable",
        actor_cpf="00011122233",
        justification="Encerramento de teste",
        skip_checks=True,
    )
    captured = capsys.readouterr()
    assert "desativado com sucesso" in captured.out

    # 5. Status final (inativo)
    call_command("canary_run", "status", skip_checks=True)
    captured = capsys.readouterr()
    assert "INATIVO" in captured.out
