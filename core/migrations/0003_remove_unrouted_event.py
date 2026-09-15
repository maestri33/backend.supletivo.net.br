from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0002_validationcheck")]

    operations = [migrations.DeleteModel(name="UnroutedEvent")]
