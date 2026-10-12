from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0044_education_declaration")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="education_state",
            field=models.CharField(blank=True, max_length=2, null=True, verbose_name="UF onde estudou"),
        )
    ]
