# Generated manually 2026-06-24
# Removes want_sanitize field - sanitization is now automatic for TTS

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("notify", "0002_notification_want_sanitize"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="notification",
            name="want_sanitize",
        ),
    ]
