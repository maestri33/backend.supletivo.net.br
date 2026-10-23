from django.db import migrations, models
from django.db.models import F
from django.db.models.functions import Now
from django.utils import timezone


def preserve_activation(apps, schema_editor):
    apps.get_model("users", "Promoter").objects.using(schema_editor.connection.alias).update(activated_at=F("created_at"))


class Migration(migrations.Migration):
    dependencies = [("users", "0041_lead_locked_pricing")]
    operations = [
        migrations.AddField(model_name="promoter", name="activated_at", field=models.DateTimeField(null=True, db_index=True)),
        migrations.RunPython(preserve_activation, migrations.RunPython.noop),
        migrations.AlterField(model_name="promoter", name="activated_at", field=models.DateTimeField(default=timezone.now, db_default=Now(), db_index=True)),
    ]
