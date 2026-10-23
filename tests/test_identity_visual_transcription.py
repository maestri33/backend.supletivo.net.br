"""Identity media bounds and account-independent transcription contract."""
import base64
import json
from io import BytesIO
from unittest.mock import ANY, AsyncMock, Mock, call

import pytest
from PIL import Image

from integrations.ai.client import ChatResult, LLMError
from integrations.ai import service


def photo():
    buffer = BytesIO()
    Image.new("RGB", (60, 40), "white").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.django_db
def test_identity_uses_one_cloudflare_call_with_all_orientations(monkeypatch):
    chat = AsyncMock(return_value=ChatResult(content='{"name":"Read Name"}'))
    monkeypatch.setattr("integrations.ai.cloudflare.connection", lambda: ("https://gateway.invalid", "test-token"))
    monkeypatch.setattr("integrations.ai.cloudflare.cloudflare_model", lambda name, default: default)
    monkeypatch.setattr("integrations.ai.cloudflare.CloudflareWorkersAIClient.chat", chat)
    data = service.read_identity_document([photo()], doc_type="rg", schema='{"name":"printed name"}', caller="test.identity")
    assert data["name"] == "Read Name"
    assert data["cpf_present"] is None
    chat.assert_awaited_once()
    messages = chat.await_args.args[0]
    content = messages[0]["content"]
    assert len([item for item in content if item["type"] == "image_url"]) == 4
    assert chat.await_args.kwargs["model"] == service.DEFAULT_IDENTITY_MODEL
    assert chat.await_args.kwargs["json_mode"] is True


@pytest.mark.django_db
def test_identity_retries_unstructured_response_only_once(monkeypatch):
    chat = AsyncMock(side_effect=[ChatResult(content='unstructured'), ChatResult(content='{"name":"Read Name"}')])
    monkeypatch.setattr("integrations.ai.cloudflare.connection", lambda: ("https://gateway.invalid", "test-token"))
    monkeypatch.setattr("integrations.ai.cloudflare.CloudflareWorkersAIClient.chat", chat)
    data = service.read_identity_document([photo()], doc_type="rg", schema='{"name":"printed name"}', caller="test.identity")
    assert data["name"] == "Read Name"
    assert chat.await_count == 2


@pytest.mark.django_db
def test_identity_stops_after_two_unstructured_responses(monkeypatch):
    chat = AsyncMock(return_value=ChatResult(content='unstructured'))
    monkeypatch.setattr("integrations.ai.cloudflare.connection", lambda: ("https://gateway.invalid", "test-token"))
    monkeypatch.setattr("integrations.ai.cloudflare.CloudflareWorkersAIClient.chat", chat)
    with pytest.raises(LLMError):
        service.read_identity_document([photo()], doc_type="rg", schema='{}', caller="test.identity")
    assert chat.await_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize('retryable,attempts', [(True, 2), (False, 1)])
def test_identity_transport_retries_are_bounded(monkeypatch, retryable, attempts):
    chat = AsyncMock(side_effect=LLMError('controlled failure', retryable=retryable))
    monkeypatch.setattr("integrations.ai.cloudflare.connection", lambda: ("https://gateway.invalid", "test-token"))
    monkeypatch.setattr("integrations.ai.cloudflare.CloudflareWorkersAIClient.chat", chat)
    with pytest.raises(LLMError):
        service.read_identity_document([photo()], doc_type="rg", schema='{}', caller="test.identity")
    assert chat.await_count == attempts


@pytest.mark.parametrize("images,doc_type", [([], "rg"), ([b"x"] * 3, "rg"), ([b"x"], "passport")])
def test_identity_rejects_unbounded_or_unsupported_inputs(images, doc_type):
    with pytest.raises(ValueError):
        service.read_identity_document(images, doc_type=doc_type, schema="{}", caller="test.identity")


def test_cnh_uses_cloudflare_ocr_without_duplicate_qr_views(monkeypatch):
    monkeypatch.setattr(service, "ocr", lambda *args, **kwargs: "Printed CNH OCR")
    monkeypatch.setattr(service, "_read_cnh_credentials", lambda *args, **kwargs: {
        "number": "00123456789", "category": "AB",
    })
    received = {}
    def extracted(prompt, **kwargs):
        received["prompt"] = prompt
        return {"name": "Printed Name", "cpf": None}
    monkeypatch.setattr(service, "generate_json", extracted)
    data = service.read_identity_document([photo()], doc_type="cnh", schema="{}", caller="test.identity")
    assert data["cpf_present"] is True
    assert data["ocr_text"] == "Printed CNH OCR"
    assert "Printed CNH OCR" in received["prompt"]


def test_cnh_visual_credentials_override_only_number_and_category(monkeypatch):
    images = [photo(), photo()]
    ocr = Mock(side_effect=["Printed front OCR", "Printed back OCR"])
    extracted = {
        "name": "Synthetic Holder", "cpf": "00000000191", "birth_date": "1980-01-02",
        "expires_on": "2035-02-03", "mother_name": "Synthetic Mother",
        "number": "1234567 SESP/PR", "category": "C", "national_register": "00123456789",
    }
    credentials = Mock(return_value={"number": "00123456789", "category": "AB"})
    monkeypatch.setattr(service, "ocr", ocr)
    monkeypatch.setattr(service, "generate_json", lambda *args, **kwargs: extracted.copy())
    monkeypatch.setattr(service, "_read_cnh_credentials", credentials)

    data = service.read_identity_document(images, doc_type="cnh", schema="{}", caller="test.identity")

    assert data == {
        "name": "Synthetic Holder", "cpf": "00000000191", "birth_date": "1980-01-02",
        "expires_on": "2035-02-03", "mother_name": "Synthetic Mother",
        "number": "00123456789", "category": "AB", "national_register": None,
        "cpf_present": True, "ocr_text": "Printed front OCR\n\n--- PRÓXIMA IMAGEM ---\n\nPrinted back OCR",
    }
    credentials.assert_called_once_with(images, caller="test.identity", deadline=ANY)
    assert ocr.call_args_list == [
        call(images[0], caller="test.identity", document=True, deadline=ANY),
        call(images[1], caller="test.identity", document=True, deadline=ANY),
    ]


@pytest.mark.parametrize("read_value,expected", [
    ("pr123456789", "PR123456789"), ("PR12345678", None),
    ("00123456789", None), (None, None),
])
def test_cnh_does_not_fill_uncertain_or_numeric_renach(monkeypatch, read_value, expected):
    monkeypatch.setattr(service, "ocr", lambda *args, **kwargs: "Printed CNH OCR")
    monkeypatch.setattr(service, "generate_json", lambda *args, **kwargs: {"national_register": read_value})
    monkeypatch.setattr(service, "_read_cnh_credentials", lambda *args, **kwargs: {
        "number": "00123456789", "category": "AB",
    })

    data = service.read_identity_document([photo()], doc_type="cnh", schema="{}", caller="test.identity")

    assert data["national_register"] == expected


def test_cnh_does_not_return_scout_data_when_visual_credentials_fail(monkeypatch):
    monkeypatch.setattr(service, "ocr", lambda *args, **kwargs: "Printed CNH OCR")
    monkeypatch.setattr(service, "generate_json", lambda *args, **kwargs: {
        "name": "Synthetic Holder", "number": "1234567 SESP/PR", "category": "B",
    })
    failure = LLMError("Controlled unreadable credential", retryable=False)
    monkeypatch.setattr(service, "_read_cnh_credentials", Mock(side_effect=failure))

    with pytest.raises(LLMError) as caught:
        service.read_identity_document([photo()], doc_type="cnh", schema="{}", caller="test.identity")

    assert caught.value is failure


@pytest.fixture
def cnh_chat(monkeypatch):
    chat = AsyncMock(return_value=ChatResult(content='{"number":"00123456789","category":"AB"}'))
    monkeypatch.setattr("integrations.ai.cloudflare.connection", lambda: ("https://gateway.invalid", "test-token"))
    monkeypatch.setattr("integrations.ai.cloudflare.cloudflare_model", lambda name, default: default)
    monkeypatch.setattr("integrations.ai.cloudflare.CloudflareWorkersAIClient.chat", chat)
    return chat


@pytest.mark.django_db
@pytest.mark.parametrize("sources,expected_views", [(1, 5), (2, 10)])
def test_cnh_credentials_use_complete_source_and_four_quadrants(cnh_chat, sources, expected_views):
    cnh_chat.return_value = ChatResult(content=json.dumps({
        "number": "00123456789", "category": "AB", "name": "Untrusted visual identity",
        "cpf": "99999999999", "birth_date": "1900-01-01",
    }))
    data = service._read_cnh_credentials([photo()] * sources, caller="test.identity")

    assert data == {"number": "00123456789", "category": "AB"}
    cnh_chat.assert_awaited_once()
    messages = cnh_chat.await_args.args[0]
    image_items = [item for item in messages[0]["content"] if item["type"] == "image_url"]
    assert len(image_items) == expected_views
    sizes = []
    for item in image_items:
        encoded = item["image_url"]["url"].split(",", 1)[1]
        with Image.open(BytesIO(base64.b64decode(encoded))) as view:
            sizes.append(view.size)
    assert sizes == ([(60, 40)] + [(30, 20)] * 4) * sources
    assert cnh_chat.await_args.kwargs["model"] == service.DEFAULT_IDENTITY_MODEL
    assert cnh_chat.await_args.kwargs["json_mode"] is True
    assert cnh_chat.await_args.kwargs["max_tokens"] == 512


@pytest.mark.django_db
@pytest.mark.parametrize("category", ["A", "B", "AB", "C", "AC", "D", "AD", "E", "AE", "ACC"])
def test_cnh_credentials_accept_printed_license_categories(cnh_chat, category):
    cnh_chat.return_value = ChatResult(content=json.dumps({"number": "00123456789", "category": category}))

    assert service._read_cnh_credentials([photo()], caller="test.identity") == {
        "number": "00123456789", "category": category,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("number", ["1234567 SESP/PR", "1234567890", "123456789012", None])
def test_cnh_credentials_reject_identity_number_and_invalid_registration_length(cnh_chat, number):
    cnh_chat.return_value = ChatResult(content=json.dumps({"number": number, "category": "AB"}))

    with pytest.raises(LLMError) as caught:
        service._read_cnh_credentials([photo()], caller="test.identity")

    assert caught.value.retryable is False
    cnh_chat.assert_awaited_once()


@pytest.mark.django_db
@pytest.mark.parametrize("category", ["ZZ", "ABC", "A B", None])
def test_cnh_credentials_reject_invalid_or_unreadable_category(cnh_chat, category):
    cnh_chat.return_value = ChatResult(content=json.dumps({"number": "00123456789", "category": category}))

    with pytest.raises(LLMError) as caught:
        service._read_cnh_credentials([photo()], caller="test.identity")

    assert caught.value.retryable is False
    cnh_chat.assert_awaited_once()


@pytest.mark.django_db
@pytest.mark.parametrize("response", [{"category": "AB"}, {"number": "00123456789"}, {}])
def test_cnh_credentials_reject_missing_registration_or_category(cnh_chat, response):
    cnh_chat.return_value = ChatResult(content=json.dumps(response))

    with pytest.raises(LLMError) as caught:
        service._read_cnh_credentials([photo()], caller="test.identity")

    assert caught.value.retryable is False
    cnh_chat.assert_awaited_once()


@pytest.mark.django_db
def test_cnh_credentials_retry_unstructured_response_only_once(cnh_chat):
    cnh_chat.side_effect = [ChatResult(content="unstructured"), cnh_chat.return_value]

    assert service._read_cnh_credentials([photo()], caller="test.identity") == {
        "number": "00123456789", "category": "AB",
    }
    assert cnh_chat.await_count == 2


@pytest.mark.django_db
def test_cnh_credentials_stop_after_two_unstructured_responses(cnh_chat):
    cnh_chat.return_value = ChatResult(content="unstructured")

    with pytest.raises(LLMError) as caught:
        service._read_cnh_credentials([photo()], caller="test.identity")

    assert caught.value.retryable is False
    assert cnh_chat.await_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize("retryable,attempts", [(True, 2), (False, 1)])
def test_cnh_credentials_transport_retries_are_bounded(cnh_chat, retryable, attempts):
    cnh_chat.side_effect = LLMError("Controlled credential transport failure", retryable=retryable)

    with pytest.raises(LLMError):
        service._read_cnh_credentials([photo()], caller="test.identity")

    assert cnh_chat.await_count == attempts


@pytest.mark.django_db
def test_malformed_vision_answer_cannot_become_extracted_identity(monkeypatch):
    chat = AsyncMock(return_value=ChatResult(content="I cannot read this"))
    monkeypatch.setattr("integrations.ai.cloudflare.connection", lambda: ("https://gateway.invalid", "test-token"))
    monkeypatch.setattr("integrations.ai.cloudflare.cloudflare_model", lambda name, default: default)
    monkeypatch.setattr("integrations.ai.cloudflare.CloudflareWorkersAIClient.chat", chat)
    with pytest.raises(LLMError):
        service.read_identity_document([photo()], doc_type="rg", schema="{}", caller="test.identity")
