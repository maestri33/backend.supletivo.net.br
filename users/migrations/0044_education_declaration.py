from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0043_checkout_paid_at")]

    operations = [
        *[
            migrations.AddField(
                model_name=model,
                name=name,
                field=field,
            )
            for model in ("candidate", "enrollment")
            for name, field in (
                ("education_declaration_accepted", models.BooleanField(default=False)),
                ("education_declaration_version", models.CharField(max_length=32, null=True, blank=True)),
                ("education_declaration_ip", models.CharField(max_length=64, null=True, blank=True)),
                ("education_declaration_user_agent", models.TextField(null=True, blank=True)),
                ("education_declaration_at", models.DateTimeField(null=True, blank=True)),
            )
        ]
    ]
