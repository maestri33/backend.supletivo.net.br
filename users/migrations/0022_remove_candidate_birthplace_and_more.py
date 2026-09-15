# Centralização da identidade no Profile (Victor 2026-06-16): filiação/estado civil/naturalidade/
# nacionalidade + chave Pix saem do Candidate/Enrollment e passam a morar SÓ no Profile.
# Ordem: adiciona no Profile → COPIA os dados existentes (não perde nada) → remove dos models.

from django.db import migrations, models

_IDENT = ("mother_name", "father_name", "marital_status", "birthplace", "nationality")


def copy_identity_to_profile(apps, schema_editor):
    """Copia a identidade que estava espalhada (Candidate/Enrollment) pro Profile — só preenche o
    que está VAZIO no Profile (não sobrescreve)."""
    Profile = apps.get_model("users", "Profile")
    Candidate = apps.get_model("users", "Candidate")
    Enrollment = apps.get_model("users", "Enrollment")

    def _into_profile(row, extra=()):
        p = Profile.objects.filter(user_id=row.user_id).first()
        if p is None:
            return
        changed = []
        for f in (*_IDENT, *extra):
            if not getattr(p, f, None) and getattr(row, f, None):
                setattr(p, f, getattr(row, f))
                changed.append(f)
        if changed:
            p.save(update_fields=changed)

    for cand in Candidate.objects.all():
        _into_profile(cand, extra=("pix_key", "pix_key_type"))
    for enr in Enrollment.objects.all():
        _into_profile(enr)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0021_enrollment_self_study_lead_self_study_and_more"),
    ]

    operations = [
        # 1) adiciona os campos de identidade no Profile (o lugar único da pessoa)
        migrations.AddField(
            model_name="profile",
            name="mother_name",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="nome da mãe"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="father_name",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="nome do pai"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="marital_status",
            field=models.CharField(
                blank=True, max_length=32, null=True, verbose_name="estado civil"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="nationality",
            field=models.CharField(
                blank=True, max_length=64, null=True, verbose_name="nacionalidade"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="birthplace",
            field=models.CharField(
                blank=True, max_length=128, null=True, verbose_name="naturalidade"
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="pix_key_type",
            field=models.CharField(
                blank=True, max_length=10, null=True, verbose_name="tipo da chave Pix"
            ),
        ),
        # 2) copia os dados que estavam espalhados ANTES de remover (não perde nada)
        migrations.RunPython(copy_identity_to_profile, migrations.RunPython.noop),
        # 3) remove os campos espalhados do Candidate e do Enrollment
        migrations.RemoveField(model_name="candidate", name="birthplace"),
        migrations.RemoveField(model_name="candidate", name="father_name"),
        migrations.RemoveField(model_name="candidate", name="marital_status"),
        migrations.RemoveField(model_name="candidate", name="mother_name"),
        migrations.RemoveField(model_name="candidate", name="nationality"),
        migrations.RemoveField(model_name="candidate", name="pix_key"),
        migrations.RemoveField(model_name="candidate", name="pix_key_type"),
        migrations.RemoveField(model_name="enrollment", name="birthplace"),
        migrations.RemoveField(model_name="enrollment", name="father_name"),
        migrations.RemoveField(model_name="enrollment", name="marital_status"),
        migrations.RemoveField(model_name="enrollment", name="mother_name"),
        migrations.RemoveField(model_name="enrollment", name="nationality"),
    ]
