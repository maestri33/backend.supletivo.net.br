# Funil do lead v2 (protótipo 2026-07-18): a conta nasce no passo do TELEFONE, sem CPF —
# o CPF entra no passo 3 (`auth.confirm_identity`). `unique` segue valendo entre não-nulos.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0033_otpcode_notification_fk_to_uuid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="cpf",
            field=models.CharField(
                blank=True, max_length=11, null=True, unique=True, verbose_name="CPF"
            ),
        ),
    ]
