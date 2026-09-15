"""Lógica do candidate (funil do colaborador) - Fachada Modular.

Espelho do lead+enrollment: captação → perfil → endereço(ViaCEP) → RG/CNH → Pix → selfie(IA) → vira PROMOTOR.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
import structlog
from users.auth.models import User
from users.exceptions import Conflict, DomainError, Forbidden, NotFound
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles import _address_proof, _document_ai, _selfie
from users.documents import service as documents_iface
from hub import interface as hub_iface
from users.auth import service as auth_iface
from users.roles.candidate.models import Candidate

from users.roles.candidate.address_proof import (
    run_address_proof_validation,
    submit_address_proof_kinship,
    upload_address_proof,
)
from users.roles.candidate.capture import (
    _ensure_candidate_inner,
    _resolve_capture_hub,
    check_or_capture,
    check_or_capture_candidate,
    create_candidate,
    ensure_candidate,
    join_candidate,
)
from users.roles.candidate.common import (
    _ADDRESS_FIELDS,
    _COLLABORATOR_ROLES,
    _DOC_DOC_FIELDS,
    _DOC_SLOT_FIELD,
    _DOC_SLOT_SIDE,
    _EDU_LEVELS,
    _EDU_QUALIFICATIONS,
    _MIME_BY_EXT,
    _PROFILE_FIELDS,
    _S,
    _SELFIE_EXT,
    CandidateError,
    _require,
    _set_status,
    get_for_user_external_id,
    logger,
)
from users.roles.candidate.coordinator import (
    _notify_candidate_rejected,
    _notify_doc_type_reset,
    approve_candidate,
    reject_candidate,
    reset_doc_type,
)
from users.roles.candidate.coordinator_queries import (
    _candidate_document_dict,
    candidate_detail_for_coordinator,
    candidate_selfie_for_coordinator,
    list_awaiting_approval_for_hub,
    list_selfie_reviews_for_hub,
)
from users.roles.candidate.documents import (
    _advance_documents,
    _doc_section_dict,
    _doc_started_at,
    _doc_value_present,
    _reconcile_stale_analyses,
    _required_doc_fields,
    _reset_doc_validation,
    get_document_section,
    patch_document_section,
    set_documents,
    upload_document_photo,
)
from users.roles.candidate.documents_ai import (
    _apply_doc_extracted,
    _doc_approved_images,
    _doc_extract_and_finish,
    _doc_post_approval,
    _finish_doc,
    run_document_fill,
    run_document_validation,
)
from users.roles.candidate.documents_decision import (
    _notify_doc_event,
    _sweep_stale_reviews,
    decide_document,
    list_document_reviews_for_hub,
)
from users.roles.candidate.education_pix import (
    set_education,
    set_pix,
)
from users.roles.candidate.profile_address import (
    _advance_address,
    get_address,
    set_address_cep,
    set_address_data,
    set_profile,
)
from users.roles.candidate.promotion import (
    _complete_candidate,
    _notify_became_promoter,
    _promote_to_promoter,
)
from users.roles.candidate.selfie import (
    _notify_selfie_approved,
    _notify_selfie_rejected,
    _notify_selfie_review,
    _selfie_ack,
    _selfie_dict,
    decide_selfie,
    get_selfie,
    set_selfie,
)
from users.roles.candidate.selfie_ai import (
    _resolve_selfie,
    _save_selfie,
    age_stale_selfies,
    run_selfie_validation,
)
from users.roles.candidate.serializers import (
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
    "roles",
    "_address_proof",
    "_document_ai",
    "_selfie",
    "documents_iface",
    "hub_iface",
    "auth_iface",
    "Candidate",
    "CandidateError",
    "_S",
    "_SELFIE_EXT",
    "_COLLABORATOR_ROLES",
    "_ADDRESS_FIELDS",
    "_PROFILE_FIELDS",
    "_EDU_LEVELS",
    "_EDU_QUALIFICATIONS",
    "_DOC_SLOT_FIELD",
    "_DOC_SLOT_SIDE",
    "_MIME_BY_EXT",
    "_DOC_DOC_FIELDS",
    "logger",
    "get_for_user_external_id",
    "_require",
    "_set_status",
    "to_dict",
    "me_dict",
    "_resolve_capture_hub",
    "check_or_capture",
    "create_candidate",
    "check_or_capture_candidate",
    "_ensure_candidate_inner",
    "join_candidate",
    "ensure_candidate",
    "set_profile",
    "get_address",
    "set_address_cep",
    "set_address_data",
    "_advance_address",
    "set_documents",
    "get_document_section",
    "patch_document_section",
    "upload_document_photo",
    "upload_address_proof",
    "submit_address_proof_kinship",
    "run_address_proof_validation",
    "_doc_started_at",
    "_reconcile_stale_analyses",
    "_doc_section_dict",
    "_required_doc_fields",
    "_doc_value_present",
    "_reset_doc_validation",
    "_advance_documents",
    "run_document_validation",
    "_doc_approved_images",
    "_doc_extract_and_finish",
    "_apply_doc_extracted",
    "_finish_doc",
    "_doc_post_approval",
    "run_document_fill",
    "decide_document",
    "_notify_doc_event",
    "_sweep_stale_reviews",
    "list_document_reviews_for_hub",
    "set_pix",
    "set_education",
    "get_selfie",
    "set_selfie",
    "_selfie_ack",
    "_selfie_dict",
    "age_stale_selfies",
    "run_selfie_validation",
    "_save_selfie",
    "_resolve_selfie",
    "_notify_selfie_approved",
    "_promote_to_promoter",
    "_complete_candidate",
    "decide_selfie",
    "_notify_selfie_rejected",
    "_notify_selfie_review",
    "reset_doc_type",
    "_notify_doc_type_reset",
    "approve_candidate",
    "reject_candidate",
    "_notify_became_promoter",
    "_notify_candidate_rejected",
    "_candidate_document_dict",
    "candidate_detail_for_coordinator",
    "list_awaiting_approval_for_hub",
    "list_selfie_reviews_for_hub",
    "candidate_selfie_for_coordinator",
]
