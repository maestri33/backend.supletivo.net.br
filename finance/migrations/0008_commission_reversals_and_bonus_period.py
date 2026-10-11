from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0007_add_manual_commission_source")]
    operations = [
        migrations.AlterField(model_name="paymentrequest", name="status", field=models.CharField(max_length=16, db_index=True, default="queued", choices=[("queued", "na fila"), ("awaiting_pix", "sem chave PIX"), ("submitted", "enviada"), ("awaiting_balance", "sem saldo"), ("paid", "paga"), ("failed", "falhou"), ("cancelled", "cancelada")])),
        migrations.AddField(model_name="commission", name="bonus_period_start", field=models.DateField(null=True, blank=True, db_index=True)),
        migrations.AlterField(model_name="commission", name="source_type", field=models.CharField(max_length=10, db_index=True, choices=[("lead", "lead pagou"), ("veteran", "student→veteran"), ("bonus", "bônus de meta"), ("manual", "avulso / manual"), ("reversal", "desconto de comissão estornada")])),
    ]
