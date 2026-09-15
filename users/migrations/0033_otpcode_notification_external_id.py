# NO-OP — reconciliação da corrida entre duas sessões no mesmo branch (2026-07-18/19).
#
# Esta migração foi aplicada em PRODUÇÃO via `--fake` (nunca executou SQL): a migração irmã
# `0033_otpcode_notification_fk_to_uuid` (de outra sessão, funil v2) chegou primeiro e já tinha
# feito o AddField+RunPython+RemoveField completo quando esta foi reconciliada. Mantida como
# checkpoint vazio só porque o nome já está gravado em `django_migrations` na produção real —
# removê-la quebraria `showmigrations`/`migrate --check` lá. Em bancos NOVOS (CI, staging do
# zero), quem cria o schema físico é a cadeia `0033_otpcode_notification_fk_to_uuid` →
# `0034_profile_cpf_nullable`; esta e a `0034_remove_otpcode_notification` são só marcadores.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("notify", "0001_initial"),
        ("users", "0032_validationblock"),
    ]

    operations = []
