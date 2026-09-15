from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0035_merge_notify_fase2_e_funil_v2")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_test",
            field=models.BooleanField(
                db_index=True, default=False, verbose_name="dado sintético de teste"
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="test_expires_at",
            field=models.DateTimeField(
                blank=True, db_index=True, null=True, verbose_name="expira em"
            ),
        ),
    ]
