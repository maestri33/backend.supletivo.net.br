"""Race de OTP e índice do webhook."""

from unittest.mock import MagicMock

import pytest
from django.db import IntegrityError
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ───────────── baixa/#33: race na 1ª emissão de OTP ─────────────
def test_otp_race_no_primeiro_pedido_vira_429_nao_500():
    """Clique duplo: os dois requests veem 'sem rate-limit', ambos tentam criar → o 2º viola a
    unique. Antes: IntegrityError → 500. Agora: re-processa e a janela bloqueia com RateLimited (429)."""
    from users.auth.otp import service as otp
    from users.exceptions import RateLimited

    now = timezone.now()
    fake_row = MagicMock()
    fake_row.last_created_at = (
        now  # recém-criado pelo "outro request" → dentro da janela curta
    )
    fake_row.hourly_window_start = now
    fake_row.hourly_count = 1

    mgr = MagicMock()
    # 1ª leitura: None (o INSERT do outro ainda não aconteceu); 2ª (recursão): o row existe
    mgr.select_for_update.return_value.filter.return_value.first.side_effect = [
        None,
        fake_row,
    ]
    mgr.create.side_effect = IntegrityError("unique violation (race)")

    import unittest.mock as m

    with m.patch.object(otp, "OtpRateLimit", MagicMock(objects=mgr)):
        with pytest.raises(RateLimited):
            otp._check_and_record_rate_limit(user=MagicMock())


# ───────────── baixa: índice no lookup do webhook ─────────────
def test_provider_payment_id_indexado():
    """O webhook de pagamento busca Checkout por provider_payment_id — precisa de índice."""
    from users.roles.lead.models import Checkout

    field = Checkout._meta.get_field("provider_payment_id")
    assert field.db_index, "provider_payment_id sem índice — webhook faz full scan"
