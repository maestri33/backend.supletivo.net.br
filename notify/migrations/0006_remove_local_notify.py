from django.db import migrations


class Migration(migrations.Migration):
    # O histórico de users ainda precisa de Notification para converter a FK de OTP
    # em UUID. Só remova as tabelas locais depois dessa cadeia terminar.
    dependencies = [
        ("notify", "0005_alter_notification_email_status_and_more"),
        ("users", "0035_merge_notify_fase2_e_funil_v2"),
    ]

    operations = [
        migrations.DeleteModel(name="Trigger"),
        migrations.DeleteModel(name="Template"),
        migrations.DeleteModel(name="Notification"),
    ]
