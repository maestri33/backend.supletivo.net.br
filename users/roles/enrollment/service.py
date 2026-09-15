"""Lógica do enrollment (funil da matrícula escolar) - Fachada Modular.

Lead pagou → cria Enrollment(STARTED) → endereço(ViaCEP) → RG(IA) → escolaridade → selfie(IA) →
coordenador aprova → paga taxa (Pix na hora ou agendado no fechamento) → vira ALUNO.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
import structlog
from users.auth.models import User
from users.exceptions import Conflict, DomainError, Forbidden, NotFound
from users.address import interface as address_iface
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles import _address_proof, _analysis, _document_ai, _selfie
from users.documents import service as documents_iface
from hub import interface as hub_iface
from users.auth import service as auth_iface
from users.roles.enrollment.models import Enrollment

from users.roles.enrollment.address_proof import (
    decide_address_proof_kinship,
    run_address_proof_validation,
    submit_address_proof_kinship,
    upload_address_proof,
)
from users.roles.enrollment.common import (
    _ADDRESS_FIELDS,
    _EDUCATION_FIELDS,
    _PROFILE_FIELDS,
    _S,
    _SELFIE_EXT,
    EnrollmentError,
    _advance_to,
    _has_education,
    _require,
    _set_status,
    get_by_external_id,
    get_for_user_external_id,
    logger,
    public_status,
)
from users.roles.enrollment.coordinator import (
    _enrollment_for_coordinator,
    _hub_item_dict,
    _notify_credentials,
    _notify_released,
    _sweep_stale_reviews,
    coordinated_user_ext,
    coordinator_correct_identity,
    detail_for_hub,
    list_for_hub,
    list_for_staff,
    list_reviews_for_hub,
)
from users.roles.enrollment.creation import (
    create_from_lead,
)
from users.roles.enrollment.education import (
    get_education,
    set_education,
)
from users.roles.enrollment.fees import (
    _plan_fee_qr,
    _queue_fee,
    conclude,
    pay_fee,
    schedule_fee,
)
from users.roles.enrollment.fees_events import (
    _fee_dict,
    _fee_due_ref,
    _fee_now_ref,
    _notify_fee_event,
    apply_fee_paid,
    apply_fee_problem,
    batch_fee_facts,
    fee_facts,
)
from users.roles.enrollment.profile_address import (
    _advance_address,
    get_address,
    set_address_cep,
    set_address_data,
)
from users.roles.enrollment.rg import (
    _advance_rg,
    _public_rg_reason,
    _reconcile_stale_analyses,
    _reset_rg_validation,
    _rg_section_dict,
    _rg_started_at,
    get_rg_section,
    patch_rg_section,
    selfie_ack,
    upload_rg_photo,
)
from users.roles.enrollment.rg_ai import (
    _rg_approved_images,
    run_rg_validation,
)
from users.roles.enrollment.rg_extraction import (
    _apply_rg_extracted,
    _finish_rg,
    _rg_extract_and_finish,
    _rg_post_approval,
    run_rg_fill,
)
from users.roles.enrollment.rg_decision import (
    _notify_resolution,
    _notify_rg_approved,
    _notify_rg_rejected,
    _notify_rg_review,
    _resume_link,
    decide_rg,
)
from users.roles.enrollment.selfie import (
    _require_rg_ready_for_selfie,
    _selfie_dict,
    get_selfie,
    set_selfie,
)
from users.roles.enrollment.selfie_ai import (
    _advance_to_release,
    _notify_coordinator_awaiting,
    _notify_selfie_approved,
    _notify_selfie_rejected,
    _notify_selfie_review,
    _resolve_selfie,
    _save_selfie,
    _save_selfie_audit,
    age_stale_selfies,
    decide_selfie,
    run_selfie_validation,
)
from users.roles.enrollment.serializers import (
    _address_dict,
    me_dict,
    to_dict,
)

__all__ = [
    "settings",
    "transaction",
    "structlog",
    "User",
    "Conflict",
    "DomainError",
    "Forbidden",
    "NotFound",
    "profiles",
    "address_iface",
    "roles",
    "_address_proof",
    "_analysis",
    "_document_ai",
    "_selfie",
    "documents_iface",
    "hub_iface",
    "auth_iface",
    "Enrollment",
    "EnrollmentError",
    "_S",
    "_ADDRESS_FIELDS",
    "_PROFILE_FIELDS",
    "_EDUCATION_FIELDS",
    "_SELFIE_EXT",
    "logger",
    "get_by_external_id",
    "get_for_user_external_id",
    "_require",
    "_set_status",
    "_rg_started_at",
    "_reconcile_stale_analyses",
    "age_stale_selfies",
    "public_status",
    "to_dict",
    "me_dict",
    "_has_education",
    "_advance_to",
    "_address_dict",
    "get_address",
    "set_address_cep",
    "set_address_data",
    "_advance_address",
    "upload_address_proof",
    "submit_address_proof_kinship",
    "decide_address_proof_kinship",
    "run_address_proof_validation",
    "_public_rg_reason",
    "_rg_section_dict",
    "get_rg_section",
    "patch_rg_section",
    "upload_rg_photo",
    "selfie_ack",
    "_advance_rg",
    "_reset_rg_validation",
    "run_rg_validation",
    "_rg_approved_images",
    "_rg_extract_and_finish",
    "_apply_rg_extracted",
    "_finish_rg",
    "_rg_post_approval",
    "run_rg_fill",
    "decide_rg",
    "_resume_link",
    "_notify_resolution",
    "_notify_rg_rejected",
    "_notify_rg_review",
    "_notify_rg_approved",
    "get_education",
    "set_education",
    "_selfie_dict",
    "get_selfie",
    "set_selfie",
    "_require_rg_ready_for_selfie",
    "run_selfie_validation",
    "_resolve_selfie",
    "_advance_to_release",
    "decide_selfie",
    "_notify_selfie_rejected",
    "_notify_selfie_approved",
    "_notify_selfie_review",
    "_save_selfie_audit",
    "_save_selfie",
    "_notify_coordinator_awaiting",
    "_fee_now_ref",
    "_fee_due_ref",
    "_fee_dict",
    "fee_facts",
    "batch_fee_facts",
    "_enrollment_for_coordinator",
    "_plan_fee_qr",
    "_queue_fee",
    "pay_fee",
    "schedule_fee",
    "conclude",
    "apply_fee_paid",
    "apply_fee_problem",
    "_notify_fee_event",
    "_hub_item_dict",
    "list_for_staff",
    "list_for_hub",
    "coordinated_user_ext",
    "detail_for_hub",
    "coordinator_correct_identity",
    "_sweep_stale_reviews",
    "list_reviews_for_hub",
    "_notify_released",
    "_notify_credentials",
    "create_from_lead",
]
