from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0042_promoter_activated_at")]

    operations = [
        migrations.AddField(
            model_name="checkout",
            name="paid_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
