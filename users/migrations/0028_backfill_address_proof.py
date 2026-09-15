# Backfill do AddressProof: os sub-docs nascem TODOS no provisionamento (documents.create_empty),
# mas usuários existentes já passaram por lá — sem esta linha, `document.address_proof` levanta
# RelatedObjectDoesNotExist em todo /me antigo.

from django.db import migrations


def create_missing_address_proofs(apps, schema_editor):
    Document = apps.get_model("users", "Document")
    AddressProof = apps.get_model("users", "AddressProof")
    missing = Document.objects.filter(address_proof__isnull=True)
    AddressProof.objects.bulk_create(
        [AddressProof(document=doc) for doc in missing.iterator()],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0027_submission_audio_addressproof"),
    ]

    operations = [
        migrations.RunPython(create_missing_address_proofs, migrations.RunPython.noop),
    ]
