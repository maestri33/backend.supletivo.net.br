from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("asaas", "0002_alter_payment_kind")]

    operations = [migrations.DeleteModel(name="OutboundJob")]
