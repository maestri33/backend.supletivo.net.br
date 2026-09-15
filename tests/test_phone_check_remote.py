"""Testes do phone/check no notify-server.

Mocka a `notify.sdk.client.phone_check_async` (ponto único de rede do caminho remote).
Cobrem: variantes BR no payload, primeiro exists → resolvido, nenhum → (False, original),
cache de módulo (positivo E negativo, TTL 1h) e o mapeamento de erro que preserva os 3
tratamentos por caller (register best-effort / change_phone estrito / TEST_MODE intocado).
"""

import asyncio

import httpx
import pytest

from notify.sdk.client import NotifyServerError
from users.auth import service
from users.exceptions import IntegrationError

_VALID_CPF = "52998224725"


@pytest.fixture
def remote_phone(settings):
    """Liga o caminho remote de verdade: TEST_MODE off (o conftest liga) + cache limpo."""
    settings.TEST_MODE = False
    settings.NOTIFY_SERVER_URL = "http://notify.test"
    settings.NOTIFY_API_KEY = "test-key"
    settings.NOTIFY_TIMEOUT = 5.0
    service._remote_check_cache.clear()
    yield settings
    service._remote_check_cache.clear()


@pytest.fixture
def sdk_mock(monkeypatch):
    """Fake da phone_check_async: grava payloads e devolve/levanta o que estiver enfileirado."""
    state = {"calls": [], "responses": []}

    async def fake_phone_check_async(numbers):
        state["calls"].append(list(numbers))
        result = state["responses"].pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("notify.sdk.client.phone_check_async", fake_phone_check_async)
    return state


def test_variantes_br_no_payload(remote_phone, sdk_mock):
    """Mobile BR vira UM POST com as duas variantes (com 9 / sem 9), nessa ordem."""
    sdk_mock["responses"].append([])
    service._check_phone_whatsapp("5543996648750")
    assert sdk_mock["calls"] == [["5543996648750", "554396648750"]]


def test_primeiro_exists_e_o_resolvido(remote_phone, sdk_mock):
    """Primeiro item com exists=True define o número resolvido (mesmo vindo depois de um False)."""
    sdk_mock["responses"].append(
        [
            {"number": "5543996648750", "exists": False},
            {"number": "554396648750", "exists": True},
        ]
    )
    assert service._check_phone_whatsapp("5543996648750") == (True, "554396648750")


def test_nenhum_exists_devolve_original(remote_phone, sdk_mock):
    """Nenhuma variante no WhatsApp → (False, telefone original)."""
    sdk_mock["responses"].append(
        [
            {"number": "5543996648750", "exists": False},
            {"number": "554396648750", "exists": False},
        ]
    )
    assert service._check_phone_whatsapp("5543996648750") == (False, "5543996648750")


def test_cache_positivo_evita_segundo_post(remote_phone, sdk_mock):
    """Resultado positivo entra no cache de módulo — segunda chamada não faz HTTP."""
    sdk_mock["responses"].append([{"number": "554396648750", "exists": True}])
    first = service._check_phone_whatsapp("5543996648750")
    second = service._check_phone_whatsapp("5543996648750")
    assert first == second == (True, "554396648750")
    assert len(sdk_mock["calls"]) == 1


def test_cache_negativo_tambem_cacheia(remote_phone, sdk_mock):
    """Negativo TAMBÉM é cacheado (análogo ao _br_jid_cache) — sem re-POST por 1h."""
    sdk_mock["responses"].append([{"number": "5543996648750", "exists": False}])
    first = service._check_phone_whatsapp("5543996648750")
    second = service._check_phone_whatsapp("5543996648750")
    assert first == second == (False, "5543996648750")
    assert len(sdk_mock["calls"]) == 1


def test_cache_expirado_refaz_o_post(remote_phone, sdk_mock, monkeypatch):
    """Entrada mais velha que o TTL é descartada e o POST refeito."""
    sdk_mock["responses"].append([{"number": "554396648750", "exists": True}])
    service._check_phone_whatsapp("5543996648750")
    stale = service._remote_check_cache["5543996648750"]
    service._remote_check_cache["5543996648750"] = (
        stale[0],
        stale[1] - service._REMOTE_CHECK_TTL_S - 1,
    )
    sdk_mock["responses"].append([{"number": "554396648750", "exists": False}])
    assert service._check_phone_whatsapp("5543996648750") == (False, "5543996648750")
    assert len(sdk_mock["calls"]) == 2


def test_erro_do_servidor_vira_phone_service_down(remote_phone, sdk_mock):
    """NotifyServerError → WhatsAppError → IntegrationError PHONE_SERVICE_DOWN (contrato mantido)."""
    sdk_mock["responses"].append(NotifyServerError(500, {"detail": "boom"}))
    with pytest.raises(IntegrationError) as exc:
        service._check_phone_whatsapp("5543996648750")
    assert exc.value.code == "PHONE_SERVICE_DOWN"


def test_erro_de_conexao_vira_phone_service_down(remote_phone, sdk_mock):
    """httpx (conexão/timeout) → mesmo mapeamento — caller não distingue transporte."""
    sdk_mock["responses"].append(httpx.ConnectError("connection refused"))
    with pytest.raises(IntegrationError) as exc:
        service._check_phone_whatsapp("5543996648750")
    assert exc.value.code == "PHONE_SERVICE_DOWN"


def test_erro_nao_cacheia(remote_phone, sdk_mock):
    """Falha NÃO entra no cache — próxima chamada tenta o servidor de novo."""
    sdk_mock["responses"].append(NotifyServerError(502, "bad gateway"))
    with pytest.raises(IntegrationError):
        service._check_phone_whatsapp("5543996648750")
    sdk_mock["responses"].append([{"number": "554396648750", "exists": True}])
    assert service._check_phone_whatsapp("5543996648750") == (True, "554396648750")
    assert len(sdk_mock["calls"]) == 2


# ── SDK real transport (client.phone_check_async, um nível abaixo do fio) ───────
#
# Os testes acima mockam `notify.sdk.client.phone_check_async` — um nível ACIMA do fio real,
# então um typo dentro do PRÓPRIO `phone_check_async` (path errado, body mal montado, header
# ausente) passaria 100% verde ali. Este teste mocka só o transporte (`httpx.AsyncClient.request`,
# o método que `_request_async` de fato chama) e exercita o corpo REAL de `phone_check_async`.


def test_phone_check_async_corpo_real_da_requisicao(settings, monkeypatch):
    """Mocka o transporte (httpx.AsyncClient.request) — path, body e header são os que o CÓDIGO
    de phone_check_async/_request_async realmente monta, não o que o teste presume."""
    from notify.sdk import client

    settings.NOTIFY_SERVER_URL = "http://notify.test"
    settings.NOTIFY_API_KEY = "super-secret-key"
    settings.NOTIFY_TIMEOUT = 5.0

    captured = {}

    async def fake_request(self, method, url, *, json=None, params=None, **kwargs):
        # `self` é o httpx.AsyncClient construído por `_request_async` (base_url/headers de lá);
        # `url` é o `path` literal repassado por `phone_check_async` — sem merge (o método real
        # de merge com base_url está sendo substituído por este fake).
        captured["method"] = method
        captured["path"] = str(url)
        captured["base_url"] = str(self.base_url)
        captured["json"] = json
        captured["auth_header"] = self.headers.get("authorization")
        return httpx.Response(
            200,
            json=[
                {"number": "5543996648750", "exists": False},
                {"number": "554396648750", "exists": True},
            ],
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    result = asyncio.run(client.phone_check_async(["5543996648750", "554396648750"]))

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/phone/check"  # path montado por phone_check_async
    assert (
        captured["base_url"] == "http://notify.test"
    )  # base_url montada por _request_async
    assert captured["json"] == {
        "numbers": ["5543996648750", "554396648750"]
    }  # body real montado por phone_check_async
    assert (
        captured["auth_header"] == "Bearer super-secret-key"
    )  # header montado por _request_async
    assert result == [
        {"number": "5543996648750", "exists": False},
        {"number": "554396648750", "exists": True},
    ]


def test_test_mode_curto_circuita_sem_sdk(settings, sdk_mock):
    """TEST_MODE=1 continua curto-circuitando ANTES de qualquer HTTP, mesmo em remote."""
    assert service._check_phone_whatsapp("5543996648750") == (True, "5543996648750")
    assert sdk_mock["calls"] == []


@pytest.mark.django_db
def test_register_best_effort_com_servidor_fora(remote_phone, sdk_mock, monkeypatch):
    """Register: notify-server fora → cadastro segue com o telefone original (best-effort)."""
    sdk_mock["responses"].append(NotifyServerError(503, "down"))
    monkeypatch.setattr(service, "_lookup_cpf", lambda cpf: None)
    monkeypatch.setattr(service, "_dispatch_otp", lambda user: False)
    reg = service.register(role="lead", phone="11999990002", cpf=_VALID_CPF)
    from users.profiles.models import Profile

    profile = Profile.objects.get(user__external_id=reg["external_id"])
    assert profile.phone == "5511999990002"  # original normalizado, sem resolução


@pytest.mark.django_db
def test_change_phone_estrito_propaga_erro(remote_phone, sdk_mock):
    """change_phone: notify-server fora → IntegrationError propaga (caminho estrito do staff)."""
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="5511999990003")
    sdk_mock["responses"].append(NotifyServerError(503, "down"))
    with pytest.raises(IntegrationError) as exc:
        service.change_phone(
            user_external_id=str(user.external_id), new_phone="11999990004"
        )
    assert exc.value.code == "PHONE_SERVICE_DOWN"
