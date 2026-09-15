from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0038_profile_education_trajectory")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="whatsapp_photo_url",
            field=models.TextField(
                blank=True,
                null=True,
                verbose_name="foto do WhatsApp (URL)",
            ),
        ),
    ]
