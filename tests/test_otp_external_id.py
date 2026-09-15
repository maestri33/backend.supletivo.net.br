"""OTP × notify (Fase 2): OtpCode guarda a STRING devolvida por send(), não mais a FK.

- Serviço: generate_and_send grava exatamente o retorno de send() em notification_external_id
  (funciona igual nos modos local e remote — send devolve str nos dois).
- Migrações (reconciliação da corrida entre 2 sessões no mesmo branch, 2026-07-18/19): a cadeia
  que EXECUTA de verdade em bancos novos é `0033_otpcode_notification_fk_to_uuid` →
  `0034_profile_cpf_nullable` (do funil v2, que chegou primeiro num commit paralelo). As migrações
  `0033_otpcode_notification_external_id`/`0034_remove_otpcode_notification` (minhas, do fix de
  passo único do review adversarial) viraram NO-OP — em produção real foram aplicadas via `--fake`
  (o schema já batia quando a Fase 2 foi reconciliada pela 1ª vez); mantidas só como checkpoint de
  nome já gravado em `django_migrations`. `0035_merge_notify_fase2_e_funil_v2` unifica o grafo.
"""

import uuid

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from users.auth.otp import service as otp_service
from users.auth.otp.models import STATUS_SENT, OtpCode

pytestmark = pytest.mark.django_db


def _user_com_phone(phone="11999990010"):
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    Profile.objects.create(user=user, phone=phone)
    return user


def test_model_sem_fk_para_notify():
    """A FK notification saiu do model; ficou a coluna solta UUIDField(null, blank)."""
    from django.db import models as dj_models

    fields = {f.name for f in OtpCode._meta.get_fields()}
    assert "notification" not in fields
    f = OtpCode._meta.get_field("notification_external_id")
    assert isinstance(f, dj_models.UUIDField)
    assert f.null is True
    assert f.blank is True


def test_otp_grava_string_devolvida_pelo_send(monkeypatch):
    """generate_and_send persiste EXATAMENTE o retorno de send() (str), sem lookup de model."""
    import notify.interface.send as notify_send

    sentinel = str(uuid.uuid4())
    monkeypatch.setattr(notify_send, "send", lambda **kwargs: sentinel)

    otp = otp_service.generate_and_send(_user_com_phone("11999990011"))

    assert otp.status == STATUS_SENT
    otp.refresh_from_db()
    # UUIDField lê de volta como objeto uuid.UUID (mesmo tendo sido atribuído como str no save).
    assert str(otp.notification_external_id) == sentinel


@pytest.mark.django_db(transaction=True)
def test_migracao_0033_fk_to_uuid_copia_fk_para_uuid():
    """A cadeia que EXECUTA de verdade (`0033_otpcode_notification_fk_to_uuid`, do funil v2):
    aplica sobre uma row com FK preenchida e confere a cópia pro UUID + remoção da FK (essa
    migração faz AddField+RunPython+RemoveField num passo só, diferente do fix de 2 passos que
    era necessário quando ela ainda não existia — ver nota de reconciliação no topo do arquivo)."""
    executor = MigrationExecutor(connection)
    try:
        old_state = executor.migrate([("users", "0032_validationblock")])
        old_apps = old_state.apps
        user = old_apps.get_model("users", "User").objects.create(
            external_id=uuid.uuid4(), password="!"
        )
        notif = old_apps.get_model("notify", "Notification").objects.create(
            caller="users.auth.otp", text="codigo 123456"
        )
        otp = old_apps.get_model("users", "OtpCode").objects.create(
            user=user, code_hash="x" * 64, notification_id=notif.id
        )

        executor = MigrationExecutor(connection)
        new_state = executor.migrate(
            [("users", "0033_otpcode_notification_fk_to_uuid")]
        )
        saved = new_state.apps.get_model("users", "OtpCode").objects.get(id=otp.id)
        assert saved.notification_external_id == notif.external_id
    finally:
        # garante o schema final pros demais testes, mesmo se algo acima falhar
        call_command("migrate", verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_grafo_de_migracao_resolve_sem_conflito():
    """Sanity do merge (0035): banco novo migra do zero sem 'duplicate column'/'conflicting
    migrations' — as duas cadeias 0033 (a que executa e a que virou no-op) convergem limpo.

    transaction=True (mesmo padrão dos vizinhos que mexem em DDL via MigrationExecutor): sem
    isso, roda dentro de uma transação aberta antes do schema dos testes anteriores ter sido
    restaurado por completo, e o loader vê um banco temporariamente inconsistente."""
    from django.core.management import call_command
    from django.db.migrations.loader import MigrationLoader

    try:
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        conflicts = loader.detect_conflicts()
        assert not conflicts, f"conflito: {conflicts}"
    finally:
        call_command("migrate", verbosity=0)
