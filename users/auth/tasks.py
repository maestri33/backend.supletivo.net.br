"""Persistent CPFHub jobs with leases and unlimited durable retries."""
from datetime import timedelta
from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from users.auth.models import CpfHubLookup


def enqueue_lookup(cpf, user=None):
    from core.tasks import async_task
    from django.conf import settings
    lookup, created = CpfHubLookup.objects.get_or_create(cpf=cpf)
    if user and lookup.user_id != user.pk:
        lookup.user = user
        lookup.save(update_fields=['user', 'updated_at'])
    if created:
        def publish():
            try:
                if settings.TEST_MODE:
                    async_task('users.auth.tasks.lookup_cpfhub', lookup.pk)
                else:
                    from django_q.tasks import async_task as publish_job
                    publish_job('users.auth.tasks.lookup_cpfhub', lookup.pk)
            except Exception:
                CpfHubLookup.objects.filter(pk=lookup.pk).update(last_error='queue_publish_failed', alert_pending=True)
        transaction.on_commit(publish)
    return lookup


def lookup_cpfhub(lookup_id):
    from integrations.tools.cpf.scripts import cpfhub
    from users.auth.service import _synthetic_identity
    from users.profiles.models import Profile
    from django.conf import settings
    now = timezone.now()
    with transaction.atomic():
        job = CpfHubLookup.objects.select_for_update().filter(pk=lookup_id).first()
        if not job or job.status != 'pending':
            return 'finished'
        if (job.lease_until and job.lease_until > now) or (job.next_attempt_at and job.next_attempt_at > now):
            return 'waiting'
        job.lease_until = now + timedelta(minutes=5)
        job.attempts += 1
        job.save(update_fields=['lease_until', 'attempts', 'updated_at'])
    try:
        identity = _synthetic_identity(job.cpf) if settings.TEST_MODE else async_to_sync(cpfhub.lookup)(job.cpf)
        with transaction.atomic():
            job = CpfHubLookup.objects.select_for_update().get(pk=lookup_id)
            if identity is not None:
                Profile.objects.filter(cpf=job.cpf).update(name=identity.name, gender=identity.gender, birth_date=identity.birth_date)
                job.identity_name = identity.name
                job.identity_gender = identity.gender
                job.identity_birth_date = identity.birth_date
                job.status = 'success'
            else:
                job.status = 'not_found'
            job.lease_until = None
            job.next_attempt_at = None
            job.last_error = ''
            job.last_status_code = None
            job.save()
        return job.status
    except Exception as exc:
        delay = min(3600, 60 * 2 ** min(job.attempts - 1, 6))
        CpfHubLookup.objects.filter(pk=lookup_id).update(lease_until=None,
            next_attempt_at=timezone.now() + timedelta(seconds=delay),
            last_error=type(exc).__name__, last_status_code=getattr(exc, 'status_code', None) or None,
            alert_pending=True)
        dispatch_alert(lookup_id)
        return 'retry_pending'


def dispatch_alert(lookup_id):
    from users.auth.models import User
    from notify.interface.send import send
    job = CpfHubLookup.objects.filter(pk=lookup_id, alert_pending=True).first()
    if not job:
        return
    admin = User.objects.filter(is_superuser=True, is_active=True, profile__isnull=False).first()
    if not admin:
        return
    profile = admin.profile
    try:
        import uuid
        key = str(uuid.uuid5(job.external_id, f'cpfhub-error-{job.attempts}'))
        send(text=f'CPFHub: falha na consulta {job.external_id}, tentativa {job.attempts}. Código: {job.last_status_code or "rede/fila"}. A consulta permanece na fila até recuperação.',
            caller='cpfhub.failure', phone=profile.phone, email=profile.email,
            whatsapp=bool(profile.phone), email_channel=bool(profile.email), idempotency_key=key, run_sync=True)
    except Exception:
        return
    CpfHubLookup.objects.filter(pk=lookup_id).update(alert_pending=False)


def retry_pending_lookups():
    from django_q.tasks import async_task
    now = timezone.now()
    jobs = CpfHubLookup.objects.filter(status='pending').filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    ).filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
    count = 0
    for pk in jobs.values_list('pk', flat=True)[:100]:
        try:
            async_task('users.auth.tasks.lookup_cpfhub', pk)
            count += 1
        except Exception:
            CpfHubLookup.objects.filter(pk=pk).update(last_error='queue_publish_failed', alert_pending=True)
    for pk in CpfHubLookup.objects.filter(alert_pending=True).values_list('pk', flat=True)[:100]:
        dispatch_alert(pk)
    return count
