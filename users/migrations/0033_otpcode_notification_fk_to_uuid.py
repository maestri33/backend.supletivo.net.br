# Fase 2 do desmembramento do notify (wiki/notify/servico-multi-tenant.md): OtpCode volta a
# guardar o handle UUID da Notification em vez de FK — com NOTIFY_MODE=remote a auditoria mora no
# notify-server e não há row local pra FK apontar. Espelho REVERSO da 0012 (que fez UUID→FK),
# editada à mão do mesmo jeito: cria a coluna nova, copia o vínculo, depois remove a FK — não
# perde nenhum log de OTP.

from django.db import migrations, models


def copy_fk_to_uuid(apps, schema_editor):
    """FK notification -> UUID notification_external_id (preserva a auditoria do OTP)."""
    OtpCode = apps.get_model("users", "OtpCode")
    Notification = apps.get_model("notify", "Notification")
    for otp in OtpCode.objects.exclude(notification__isnull=True):
        notif = Notification.objects.filter(id=otp.notification_id).first()
        if notif is not None:
            otp.notification_external_id = notif.external_id
            otp.save(update_fields=["notification_external_id"])


def restore_uuid_to_fk(apps, schema_editor):
    """Reverso: UUID -> FK (roda quando a FK já foi recriada ao reverter o RemoveField)."""
    OtpCode = apps.get_model("users", "OtpCode")
    Notification = apps.get_model("notify", "Notification")
    for otp in OtpCode.objects.exclude(notification_external_id__isnull=True):
        notif = Notification.objects.filter(
            external_id=otp.notification_external_id
        ).first()
        if notif is not None:
            otp.notification_id = notif.id
            otp.save(update_fields=["notification"])


class Migration(migrations.Migration):
    dependencies = [
        ("notify", "0005_alter_notification_email_status_and_more"),
        ("users", "0032_validationblock"),
    ]

    operations = [
        migrations.AddField(
            model_name="otpcode",
            name="notification_external_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(copy_fk_to_uuid, restore_uuid_to_fk),
        migrations.RemoveField(
            model_name="otpcode",
            name="notification",
        ),
    ]
