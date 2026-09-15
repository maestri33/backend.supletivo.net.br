"""Router de autenticação do grupo Staff (Superuser puro)."""

from __future__ import annotations

from ninja import Router

from api.base import add_auth_refresh
from api.schemas.auth import TokenOut
from api.staff.schemas import StaffCheckIn, StaffCheckOut, StaffLoginIn, StaffLoginPasswordIn
from users.auth import service as auth_iface

router = Router(tags=["auth"])


@router.post("/check", response=StaffCheckOut, auth=None, summary="Verificação de staff")
def staff_check(request, payload: StaffCheckIn):
    """Acha o staff (superuser) por cpf/phone/external_id e dispara OTP."""
    return auth_iface.check_staff(
        cpf=payload.cpf, phone=payload.phone, external_id=payload.external_id
    )


@router.post("/login", response=TokenOut, auth=None, summary="Login do staff (WhatsApp OTP)")
def staff_login(request, payload: StaffLoginIn):
    """Login passwordless (OTP) do staff."""
    return auth_iface.login_staff(external_id=payload.external_id, otp=payload.otp)


@router.post("/login-password", response=TokenOut, auth=None, summary="Login do staff por senha master (Contingência)")
def staff_login_password(request, payload: StaffLoginPasswordIn):
    """Login de contingência do staff via senha master."""
    return auth_iface.login_staff_password(
        identifier=payload.identifier, password=payload.password
    )


add_auth_refresh(router)
