from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0037_profile_education_details")]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="education_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("fundamental", "Ensino Fundamental"),
                    ("medio", "Ensino Médio"),
                    ("superior", "Ensino Superior"),
                ],
                max_length=16,
                null=True,
                verbose_name="escolaridade",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_last_completed_grade",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="última série/ano concluído",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_qualification",
            field=models.CharField(
                blank=True,
                max_length=32,
                null=True,
                verbose_name="última formação superior frequentada",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_last_completed_qualification",
            field=models.CharField(
                blank=True,
                max_length=32,
                null=True,
                verbose_name="última formação superior concluída",
            ),
        ),
    ]
