"""core/sentry.py — scrub de PII e no-op sem DSN.

O que estes testes garantem, em ordem de gravidade: (1) CPF/telefone não saem do processo dentro
de um evento; (2) o token de `/media/` não vira URL no painel; (3) sem DSN nada é ligado; (4)
config quebrada trava o boot em vez de passar batido. Nenhum deles precisa de banco nem de rede.
"""

from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.sentry import (
    DENYLIST,
    git_sha,
    init_sentry,
    mask_pii_text,
    redact_media_url,
    scrub_event,
)

CPF = "52998224725"  # o mesmo CPF de teste do settings (TEST_COLLABORATOR_CPF)
PHONE = "5511999990001"


# ── máscara em texto livre ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        (f"CPF {CPF} inválido", "CPF ***25 inválido"),
        ("CPF 529.982.247-25 inválido", "CPF ***25 inválido"),
        (f"whatsapp {PHONE} recusado", "whatsapp ***01 recusado"),
        ("telefone 11999990000 recusado", "telefone ***00 recusado"),
        # o formatado e o cru na MESMA string (mensagem de validação costuma trazer os dois)
        (f"{CPF} != 529.982.247-25", "***25 != ***25"),
    ],
)
def test_mascara_cpf_e_telefone(raw, expected):
    assert mask_pii_text(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "user_id=4210",  # id curto
        "epoch 1770000000",  # 10 dígitos = epoch em segundos
        "epoch_ms 1770000000000",  # 13 dígitos, NÃO começa em 55
        "valor R$ 1.234,56",
        "trace 0123456789abcdef",  # hex, não é run de dígitos
    ],
)
def test_nao_mascara_numero_que_nao_e_pii(raw):
    """A máscara tem que ser justa: cegar todo número longo tiraria o diagnóstico junto."""
    assert mask_pii_text(raw) == raw


def test_digitos_colados_num_numero_maior_ficam_intactos():
    """`(?<!\\d)`/`(?!\\d)`: 11 dígitos DENTRO de um número de 20 não é CPF."""
    assert mask_pii_text("id 12345678901234567890") == "id 12345678901234567890"


# ── /media/: o nome do arquivo é a credencial ────────────────────────────────────────────────
def test_redact_media_url_tira_o_token():
    url = "https://backend.v7m.live/media/selfie/9f3a7c1e2b.jpg"
    assert redact_media_url(url) == "https://backend.v7m.live/media/selfie/<redacted>"


def test_redact_media_url_preserva_query_string():
    url = "https://backend.v7m.live/media/documents/tok3n.png?v=2"
    assert redact_media_url(url) == (
        "https://backend.v7m.live/media/documents/<redacted>?v=2"
    )


def test_redact_media_url_ignora_url_sem_media():
    url = "https://backend.v7m.live/api/clients/pricing"
    assert redact_media_url(url) == url


# ── scrub_event: o evento inteiro ────────────────────────────────────────────────────────────
def test_scrub_event_varre_aninhado_e_a_url():
    event = {
        "request": {"url": "https://x.test/media/selfie/tok.jpg"},
        "exception": {
            "values": [
                {
                    "value": f"CPF {CPF} recusado",
                    "stacktrace": {"frames": [{"vars": {"doc": CPF}}]},
                }
            ]
        },
        "breadcrumbs": {"values": [{"message": f"otp para {PHONE}"}]},
    }

    out = scrub_event(event)

    assert out["request"]["url"] == "https://x.test/media/selfie/<redacted>"
    assert out["exception"]["values"][0]["value"] == "CPF ***25 recusado"
    # o `vars` do frame é o vazamento mais fácil de esquecer: ninguém o escreveu, o SDK o coletou
    assert out["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]["doc"] == (
        "***25"
    )
    assert out["breadcrumbs"]["values"][0]["message"] == "otp para ***01"
    assert CPF not in str(out) and PHONE not in str(out)


def test_scrub_event_mascara_contexts_e_tags_por_chave():
    """Regressão do buraco do SDK: `EventScrubber.scrub_event` visita request/extra/user/
    breadcrumbs/frames/spans e PARA — `contexts` (destino do `set_context`) e `tags` ficam de
    fora. Aqui é o único lugar que pega uma chave Pix: ela é um e-mail/string aleatória, não tem
    forma pra máscara de dígitos casar."""
    event = {
        "contexts": {"candidato": {"pix_key": "victor@pix.test", "hub": "standard"}},
        "tags": {"cpf": CPF, "rota": "/app/cpf"},
    }

    out = scrub_event(event)

    assert out["contexts"]["candidato"]["pix_key"] != "victor@pix.test"
    assert out["tags"]["cpf"] != CPF
    # o que NÃO é PII continua legível — mascarar tudo cegaria o diagnóstico junto
    assert out["contexts"]["candidato"]["hub"] == "standard"
    assert out["tags"]["rota"] == "/app/cpf"


def test_evento_mascarado_ainda_serializa_no_envelope():
    """A trava mais importante do arquivo, porque a falha é MUDA.

    O `serialize()` do cliente roda ANTES do `before_send`, então quem devolve um `AnnotatedValue`
    (o marcador de "filtrado" do próprio SDK) daqui não é traduzido por ninguém: estoura
    `TypeError` no `json.dumps` do envelope e o evento some inteiro — o painel fica vazio e ninguém
    descobre por quê. Este teste monta o envelope de verdade e exige que ele serialize.
    """
    import io

    from sentry_sdk.envelope import Envelope

    event = {
        "contexts": {"candidato": {"pix_key": "victor@pix.test"}},
        "tags": {"cpf": CPF},
        "extra": {"msg": f"cpf {CPF}"},
    }

    envelope = Envelope()
    envelope.add_event(scrub_event(event))
    buffer = io.BytesIO()
    envelope.serialize_into(buffer)  # TypeError aqui = evento perdido em produção

    wire = buffer.getvalue().decode()
    assert "[Filtered]" in wire
    assert CPF not in wire and "victor@pix.test" not in wire


def test_scrub_event_preserva_chaves_estruturais():
    """Só VALORES são mascarados — mexer nas chaves quebraria o parse do evento no Sentry."""
    out = scrub_event({"exception": {"values": [{"type": "ValueError"}]}})
    assert out == {"exception": {"values": [{"type": "ValueError"}]}}


def test_scrub_event_descarta_quando_o_scrub_falha():
    """Fail-closed: evento que não deu pra mascarar NÃO é enviado cru."""

    class Explode(dict):
        def items(self):  # estoura DENTRO do _walk, no meio da varredura
            raise RuntimeError("boom")

    assert scrub_event({"extra": Explode(a=1)}) is None


# ── init: no-op sem DSN, fail-fast com config quebrada ───────────────────────────────────────
def test_init_sem_dsn_e_noop():
    assert init_sentry(dsn="", environment="test") is False


@pytest.mark.parametrize("rate", [-0.1, 1.5])
def test_init_recusa_sample_rate_fora_da_faixa(rate):
    with pytest.raises(ImproperlyConfigured, match="SENTRY_TRACES_SAMPLE_RATE"):
        init_sentry(
            dsn="https://k@o.test/1", environment="test", traces_sample_rate=rate
        )


def test_init_recusa_request_body_invalido():
    with pytest.raises(ImproperlyConfigured, match="SENTRY_REQUEST_BODY"):
        init_sentry(dsn="https://k@o.test/1", environment="test", request_body="sempre")


# ── release = SHA do HEAD ────────────────────────────────────────────────────────────────────
def test_git_sha_devolve_o_head_do_checkout():
    """O deploy deixa o HEAD no commit validado pelo CI, então o HEAD É a release."""
    import shutil
    import subprocess
    import pytest

    if not shutil.which("git"):
        pytest.skip("git CLI não instalado no ambiente do container")

    sha = git_sha(Path(__file__).resolve().parent.parent)
    esperado = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    ).stdout.strip()

    assert sha == esperado
    assert len(sha) == 40  # SHA completo, não abreviado


def test_git_sha_fora_de_repo_git_devolve_vazio(tmp_path):
    """Best-effort: sem `.git` o Sentry só fica sem release — não é erro de boot."""
    assert git_sha(tmp_path) == ""


def test_git_sha_com_caminho_inexistente_devolve_vazio():
    """`git -C` num path que não existe sai com erro; o boot não pode cair por isso."""
    assert git_sha("/nao/existe/em/lugar/nenhum") == ""


# ── denylist ─────────────────────────────────────────────────────────────────────────────────
def test_denylist_estende_o_default_do_sdk_com_pii_do_dominio():
    """O default do SDK conhece senha/token; o CPF/pix/otp deste domínio é adição nossa."""
    assert {"password", "authorization"} <= set(DENYLIST)  # default do SDK preservado
    assert {"cpf", "pix", "otp", "rg", "phone"} <= set(DENYLIST)
