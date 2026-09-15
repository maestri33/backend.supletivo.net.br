from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0004_alter_aicall_operation")]

    operations = [
        migrations.AlterField(
            model_name="aicall",
            name="operation",
            field=models.CharField(
                choices=[
                    ("json", "json"),
                    ("summarize", "summarize"),
                    ("grade", "grade"),
                    ("vision", "vision"),
                    ("ocr", "ocr"),
                    ("stt", "stt"),
                ],
                max_length=20,
            ),
        )
    ]
