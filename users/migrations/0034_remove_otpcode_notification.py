# NO-OP — ver comentário em 0033_otpcode_notification_external_id.py (mesma reconciliação).
# O RemoveField real da FK já aconteceu via `0033_otpcode_notification_fk_to_uuid`.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0033_otpcode_notification_external_id"),
    ]

    operations = []
