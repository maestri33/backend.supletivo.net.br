"""Testes do motor local de templates de notificação e endpoints do Staff no backend."""

import pytest
from django.db import transaction
from django_q import tasks

from notify.interface import templates as tpl_iface
from notify.interface.events import send_event
from notify.models import Template, Trigger
from users.auth.models import User
from users.profiles.models import Profile


@pytest.mark.django_db
def test_template_crud_and_cache_invalidation():
    tpl = Template.objects.create(
        event="custom.welcome",
        title="Bem-vindo!",
        body_md="Olá, {nome}! Seu link é {link}.",
        channels="whatsapp",
    )
    Trigger.objects.create(template=tpl, fires_on="Ao criar conta", active=True)

    loaded = tpl_iface.get("custom.welcome")
    assert loaded is not None
    assert loaded.title == "Bem-vindo!"
    assert loaded.body_md == "Olá, {nome}! Seu link é {link}."

    rendered = tpl_iface.render(loaded.body_md, {"nome": "Victor", "link": "https://v7m.org"})
    assert rendered == "Olá, Victor! Seu link é https://v7m.org."

    # Update template and verify cache is invalidated
    tpl.body_md = "Oi, {nome}! Link: {link}."
    tpl.save()

    updated = tpl_iface.get("custom.welcome")
    assert updated.body_md == "Oi, {nome}! Link: {link}."


@pytest.mark.django_db
def test_send_event_renders_local_template_and_dispatches_via_send(monkeypatch):
    user = User.objects.create_user()
    profile = Profile.objects.create(user=user, name="Carlos Souza", phone="5543999998888")

    Template.objects.create(
        event="auth.otp",
        title="Código OTP",
        body_md="Seu código é *{codigo}*, expira em *{ttl_minutos}* min.",
        channels="whatsapp",
    )

    queued = []
    monkeypatch.setattr(transaction, "on_commit", lambda fn: fn())
    monkeypatch.setattr(tasks, "async_task", lambda *args: queued.append(args))

    ext_id = send_event(
        "auth.otp",
        profile=profile,
        ctx={"codigo": "654321", "ttl_minutos": "15"},
    )
    assert ext_id is not None
    assert len(queued) == 1
    task, payload = queued[0]
    assert task == "notify.sdk.push.push_send"
    assert payload["caller"] == "event:auth.otp"
    assert payload["phone"] == "5543999998888"
    assert payload["whatsapp"] is True
    assert "Seu código é *654321*, expira em *15* min." in payload["text"]


@pytest.mark.django_db
def test_send_event_respects_inactive_trigger(monkeypatch):
    user = User.objects.create_user()
    profile = Profile.objects.create(user=user, name="Carlos Souza", phone="5543999998888")

    tpl = Template.objects.create(
        event="lead.captured",
        title="Lead",
        body_md="Olá {nome}",
        channels="whatsapp",
    )
    Trigger.objects.create(template=tpl, active=False)

    queued = []
    monkeypatch.setattr(transaction, "on_commit", lambda fn: fn())
    monkeypatch.setattr(tasks, "async_task", lambda *args: queued.append(args))

    result = send_event("lead.captured", profile=profile)
    assert result is None
    assert len(queued) == 0


@pytest.fixture
def staff_headers():
    from users.auth.jwt import service as jwt_service
    user = User.objects.create_superuser(password="secret")
    tokens = jwt_service.issue(str(user.external_id), [])
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}


@pytest.mark.django_db
def test_staff_notify_router_endpoints(client, staff_headers, monkeypatch):
    from integrations.ai import service as ai_service
    monkeypatch.setattr(ai_service, "complete_text", lambda **kwargs: "Olá {nome}, seu código é {codigo}")

    tpl = Template.objects.create(
        event="lead.captured",
        title="Inscrição Iniciada",
        body_md="Olá, {nome}! Acesse {link}.",
        channels="whatsapp,email",
    )
    Trigger.objects.create(template=tpl, fires_on="Formulário preenchido", active=True)

    # 1. list_templates
    resp = client.get("/api/v1/staff/notify/templates", **staff_headers)
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert any(item["event"] == "lead.captured" for item in data)

    # 2. get_template
    resp = client.get("/api/v1/staff/notify/templates/lead.captured", **staff_headers)
    assert resp.status_code == 200
    assert resp.json()["event"] == "lead.captured"
    assert resp.json()["body_md"] == "Olá, {nome}! Acesse {link}."

    # 3. patch_template
    resp = client.patch(
        "/api/v1/staff/notify/templates/lead.captured",
        data={"body_md": "Olá, {nome}! Novo link: {link}."},
        content_type="application/json",
        **staff_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["body_md"] == "Olá, {nome}! Novo link: {link}."
    tpl.refresh_from_db()
    assert tpl.body_md == "Olá, {nome}! Novo link: {link}."

    # 4. preview_template
    resp = client.post(
        "/api/v1/staff/notify/templates/lead.captured/preview",
        data={"ctx": {"nome": "Victor", "link": "https://v7m.org/teste"}},
        content_type="application/json",
        **staff_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["rendered"] == "Olá, Victor! Novo link: https://v7m.org/teste."

    # 5. template_stats
    resp = client.get("/api/v1/staff/notify/templates/stats", **staff_headers)
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total"] >= 1
    assert stats["active"] >= 1

    # 6. ai_assist
    resp = client.post(
        "/api/v1/staff/notify/templates/ai-assist",
        data={"text": "Ola {nome}, seu codigo e {codigo}", "action": "improve"},
        content_type="application/json",
        **staff_headers,
    )
    assert resp.status_code == 200
    ai_data = resp.json()
    assert "{nome}" in ai_data["text"]
    assert "{codigo}" in ai_data["text"]


def test_tts_clean_text_and_synthesis(monkeypatch):
    from integrations.ai import tts

    cleaned = tts.clean_text_for_speech("Olá *{nome}*! Acesse o link: https://v7m.org/xyz")
    assert "*" not in cleaned
    assert "https://v7m.org/xyz" not in cleaned
    assert "pelo link enviado" in cleaned

    # Test synthesis with storage
    class MockResp:
        status_code = 200
        content = b"OggS-fake-audio-bytes"

    import httpx
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs: MockResp())
    monkeypatch.setattr(tts, "_get_omniroute_base_url", lambda: "http://omnirouter.internal")

    url = tts.synthesize_voice_note("Olá Victor, seu pagamento foi confirmado.")
    assert url is not None
    assert "/media/ai/tts/" in url


def test_tts_cross_gender_rule():
    """Valida a regra cruzada de gênero (Victor Rule)."""
    from integrations.ai.tts import TtsOption

    opt = TtsOption(
        model="minimax/speech-01-hd",
        voice_female="Portuguese_SereneWoman",
        voice_male="Portuguese_GentleTeacher",
    )

    # Destinatário Homem (M) -> Voz Feminina
    assert opt.voice_for("M") == "Portuguese_SereneWoman"
    assert opt.voice_for("m") == "Portuguese_SereneWoman"

    # Destinatária Mulher (F) -> Voz Masculina
    assert opt.voice_for("F") == "Portuguese_GentleTeacher"
    assert opt.voice_for("f") == "Portuguese_GentleTeacher"

    # Destinatário Desconhecido (None / vazio) -> Voz Feminina padrão
    assert opt.voice_for(None) == "Portuguese_SereneWoman"
    assert opt.voice_for("") == "Portuguese_SereneWoman"


def test_tts_chain_fallback(monkeypatch):
    """Valida que falha no 1º modelo ativa o 2º modelo na cadeia."""
    from integrations.ai import tts
    import httpx

    called_models = []

    class SimpleResp:
        def __init__(self, status_code, content=b"", text=""):
            self.status_code = status_code
            self.content = content
            self.text = text

    def mock_post(self, url, **kwargs):
        json_body = kwargs.get("json", {})
        model = json_body.get("model")
        called_models.append(model)
        if model == "minimax/speech-01-hd":
            return SimpleResp(500, text="OmniRoute upstream error")
        return SimpleResp(200, content=b"OggS-fallback-audio-bytes")

    monkeypatch.setattr(httpx.Client, "post", mock_post)
    monkeypatch.setattr(tts, "_get_omniroute_base_url", lambda: "http://omnirouter.internal")

    import uuid
    random_text = f"Texto de teste com fallback {uuid.uuid4().hex[:8]}"
    url = tts.synthesize_voice_note(
        random_text,
        gender="F",
        caller="test.fallback",
    )
    assert url is not None
    assert "/media/ai/tts/" in url
    assert "minimax/speech-01-hd" in called_models
    assert "openai/tts-1" in called_models


@pytest.mark.django_db
def test_staff_tts_config_and_probe_endpoints(client, staff_headers, monkeypatch):
    """Valida os endpoints GET /tts/config e POST /tts/probe."""
    import httpx

    class MockResp:
        status_code = 200
        content = b"OggS-probe-audio"
        text = "ok"

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs: MockResp())

    # 1. GET /api/v1/staff/notify/tts/config
    resp = client.get("/api/v1/staff/notify/tts/config", **staff_headers)
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert "omniroute_url" in data
    assert len(data["chain"]) >= 1
    assert "cross_gender_rule" in data

    # 2. POST /api/v1/staff/notify/tts/probe
    resp = client.post(
        "/api/v1/staff/notify/tts/probe",
        data={"text": "Mensagem de teste para probe de voz", "gender": "M"},
        content_type="application/json",
        **staff_headers,
    )
    assert resp.status_code == 200, resp.content
    probe_data = resp.json()
    assert probe_data["ok"] is True
    assert probe_data["gender_target"] == "M"
    assert "/media/ai/tts/" in probe_data["audio_url"]


def test_template_model_storytelling_purged():
    """Garante que storytelling foi completamente expurgado da modelagem."""
    from notify.models import Template
    field_names = [f.name for f in Template._meta.get_fields()]
    assert "storytelling" not in field_names
    assert "story_prompt" not in field_names



