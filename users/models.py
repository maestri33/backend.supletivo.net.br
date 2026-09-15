"""Ponto de entrada de models do app `users`.

Os models vivem nos sub-módulos (auth/profiles/roles/otp) pra ficar tudo "MUITO bem separado"
(CONVENTION §2), mas o autodiscovery do Django importa só `users.models`. Reimportar aqui faz o
`makemigrations` enxergar todos sob o mesmo app_label `users` (um migration set só).
"""

from users.address.models import Address
from users.auth.models import User, UserManager
from users.auth.otp.models import OtpCode, OtpRateLimit
from users.blocks.models import ValidationBlock
from users.documents.models import (
    CNH,
    RG,
    AddressProof,
    Certificate,
    Document,
    Military,
)
from users.profiles.models import Profile
from users.roles.candidate.models import Candidate
from users.roles.enrollment.models import EducationalData, Enrollment
from users.roles.lead.models import Checkout, Lead
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter
from users.roles.student.models import (
    Student,
    StudentDiploma,
    StudentDocument,
    StudentExam,
    StudentPendency,
)
from users.roles.training.models import Material, MaterialAssignment, Submission

__all__ = [
    "User",
    "UserManager",
    "Profile",
    "UserRole",
    "OtpCode",
    "OtpRateLimit",
    "Address",
    "Document",
    "RG",
    "CNH",
    "Certificate",
    "Military",
    "AddressProof",
    "Lead",
    "Checkout",
    "Enrollment",
    "EducationalData",
    "Candidate",
    "Promoter",
    "Material",
    "MaterialAssignment",
    "Submission",
    "Student",
    "StudentDocument",
    "StudentExam",
    "StudentDiploma",
    "StudentPendency",
    "ValidationBlock",
]
