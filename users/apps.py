from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "users"
    label = "users"
    verbose_name = "usuários"

    def ready(self):
        # Valida o catálogo de roles cedo (ImproperlyConfigured derruba o boot se ROLE_RULES quebrado)
        # e garante o par de chaves JWT (gera em keys/ se faltar). Registra os system checks.
        from django.core.checks import register

        from users.auth.jwt import keys
        from users.roles import catalog  # noqa: F401 — import valida ROLE_RULES no boot

        from .checks import check_users

        keys.ensure_keys()
        register(check_users)

        # Hook de pagamento do lead (CONVENTION §7.3): o webhook do asaas/infinitepay dispara
        # 'payment.paid' → o lead casa o checkout e marca pago. Registra no boot (apps já carregados).
        from core import hooks as core_hooks
        from users.roles.lead.hooks import on_payment_paid, on_payment_refunded

        core_hooks.register("payment.paid", on_payment_paid)
        core_hooks.register("payment.refunded", on_payment_refunded)

        # Hooks da TAXA da matrícula (plan/14): o worker do finance dispara 'fee.paid'/'fee.problem'
        # → a matrícula avança o status (1ª paga → fee_paid) e o COORDENADOR é notificado.
        from users.roles.enrollment.hooks import on_fee_paid, on_fee_problem

        core_hooks.register("fee.paid", on_fee_paid)
        core_hooks.register("fee.problem", on_fee_problem)

        # ValidationBlock signals: ouvem post_save em TODO model com validation_status/selfie_status.
        from django.db.models.signals import post_save

        from users.blocks.signals import _on_validation_change
        from users.documents.models import RG, CNH, AddressProof
        from users.roles.candidate.models import Candidate
        from users.roles.enrollment.models import Enrollment
        from users.roles.student.models import StudentDocument
        from users.roles.training.models import Submission

        for model in (
            RG,
            CNH,
            AddressProof,
            StudentDocument,
            Enrollment,
            Candidate,
            Submission,
        ):
            post_save.connect(_on_validation_change, sender=model)

        # Notify promoter quando um lead indicado vira aluno (Student criado).
        from users.roles.student.models import Student
        from users.roles.student.signals import on_student_created

        post_save.connect(on_student_created, sender=Student)
