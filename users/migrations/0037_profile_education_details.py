from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0036_user_test_lifecycle")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="education_city",
            field=models.CharField(
                blank=True,
                max_length=128,
                null=True,
                verbose_name="cidade onde estudou",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_grade",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="última série/ano"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_school",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="última escola"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("completed", "Concluiu"),
                    ("attending", "Está cursando"),
                    ("stopped", "Parou antes de concluir"),
                ],
                max_length=16,
                null=True,
                verbose_name="situação da última série",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="education_year",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="ano da última frequência"
            ),
        ),
    ]
