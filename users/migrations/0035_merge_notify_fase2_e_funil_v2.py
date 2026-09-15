# Merge de grafo — reconciliação da corrida entre duas sessões no mesmo branch (2026-07-18/19):
# a Fase 2 do notify (0033_otpcode_notification_external_id → 0034_remove_otpcode_notification)
# e o funil v2 do lead (0033_otpcode_notification_fk_to_uuid → 0034_profile_cpf_nullable) nasceram
# como pontas divergentes do mesmo 0032, cada uma sem saber da outra. Ambas já rodaram fisicamente
# em produção (django_migrations confirma as 4 aplicadas, schema físico bate); esta migração só
# unifica o grafo daqui pra frente — nenhuma operação real.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0034_remove_otpcode_notification"),
        ("users", "0034_profile_cpf_nullable"),
    ]

    operations = []
