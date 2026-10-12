"""Public release progress derived from enrollment facts, without internal fees."""

from users.profiles import interface as profiles
from users.roles.enrollment.models import Enrollment
from users.roles.lead.models import Checkout


def release_dict(enrollment, *, rg_status, address_proof_status) -> dict | None:
    if enrollment.status not in {
        Enrollment.Status.AWAITING_RELEASE,
        Enrollment.Status.FEE_PAID,
        Enrollment.Status.FEE_SCHEDULED,
        Enrollment.Status.COMPLETED,
    }:
        return None

    # Import the facade at call time: fees_events and serializers depend on it.
    from users.roles.enrollment import service

    hub = enrollment.hub
    coordinator_profile = profiles.get(hub.coordinator) if hub.coordinator_id else None
    facts = service.fee_facts(enrollment)
    reviewed = (
        enrollment.selfie_status == "approved"
        and enrollment.selfie_verified
        and enrollment.consent_accepted
        and rg_status == "approved"
        and address_proof_status == "approved"
    )
    if enrollment.status == Enrollment.Status.COMPLETED:
        stage = "ready"
        next_action = "Seu acesso foi liberado. Entre no painel do aluno para acessar a plataforma de estudos."
    elif not reviewed:
        stage = "document_review"
        next_action = "O polo está conferindo seu cadastro e sua identidade. Se precisar de alguma correção ou atendimento, você será orientado."
    elif not facts["first_paid"]:
        stage = "partner_setup"
        next_action = "O coordenador precisa efetivar sua matrícula na instituição parceira e preparar seu acesso para estudar."
    else:
        stage = "access_preparation"
        next_action = "O polo precisa concluir os procedimentos de matrícula e registrar seu login na plataforma da instituição parceira."

    return {
        "stage": stage,
        "next_action": next_action,
        "hub_name": hub.brand if hub.brand not in {"standard", "test", ""} else "Polo responsável",
        "coordinator_name": coordinator_profile.name if coordinator_profile else None,
        # Hub has no dedicated public contact field. Never publish a private profile phone.
        "contact_url": None,
        "updated_at": enrollment.updated_at.isoformat() if enrollment.updated_at else None,
        "payment_confirmed": Checkout.objects.filter(lead__user_id=enrollment.user_id, is_paid=True).exists(),
        # Awaiting release is owned by the coordinator. Upload routes are gated to wizard states.
        "action_required": False,
        "action_route": None,
    }
