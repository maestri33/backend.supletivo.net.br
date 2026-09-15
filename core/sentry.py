"""Sentry (ou GlitchTip) — captura de erro do monólito. **Sem `SENTRY_DSN` é NO-OP.**

Por que um módulo, e não as 10 linhas que viviam no fim do `settings.py`: o settings *declara*
config (§10); a LÓGICA de scrub mora aqui, testável fora do Django (`tests/test_sentry.py`) —
mesmo padrão do `core/environment.py` (o settings chama `resolve_environment`, a regra é testada
sozinha). O bloco antigo, além disso, era código MORTO: `sentry_sdk` nunca esteve no
`pyproject.toml`, então o primeiro `.env` com DSN derrubaria o boot no `import sentry_sdk`.

⚠️ LGPD — o que ESTE backend carrega: CPF, telefone, RG/CNH, comprovante de endereço, SELFIE e
chave Pix. Um evento de erro leva junto headers, query-string, corpo do request e as VARIÁVEIS
LOCAIS de cada frame do stack — ou seja, o CPF que estourou o `ValueError` viaja no evento. Daí
quatro camadas, todas ligadas por padrão:

1. `send_default_pii=False` (**hardcoded, não é config**): sem IP e sem cookies. Não virou flag
   de `.env` de propósito — é o tipo de chave que alguém liga "só pra debugar" e esquece ligada.
2. `max_request_body_size="never"` por padrão: o `send_default_pii=False` do SDK **gateia só os
   cookies** — o CORPO do request continua sendo capturado (até 10KB no default `medium`). Como
   o funil dá POST de cpf/telefone/endereço/pix, o corpo fica FORA por padrão. `SENTRY_REQUEST_BODY`
   afrouxa isso em dev/staging quando o corpo for o que falta pra diagnosticar.
3. `EventScrubber(recursive=True)` com denylist ESTENDIDA: o default do SDK cobre
   senha/token/cookie, mas NÃO cobre o PII do nosso domínio (cpf, phone, pix, otp, rg…).
   `recursive=True` porque o dado real vem aninhado (JSON do body, `vars` de frame).
4. `before_send`/`before_send_transaction` (= `scrub_event`): varre o evento INTEIRO mascarando o
   que escapa da denylist por não estar numa chave — CPF/telefone soltos **em texto** (mensagem de
   exceção, breadcrumb, linha de código) e o token de `/media/<arquivo>`, que neste projeto **é a
   credencial** do arquivo (mesma razão do `safe_path` do `logging_middleware`, reusado aqui).

**Fail-closed** (ao contrário do `_scrub_pii` do settings, que é fail-open): se o scrub estourar,
o evento é DESCARTADO, não enviado cru. Vazar CPF pra um terceiro é pior do que perder um evento.
Pra esse modo de falha não virar "Sentry silencioso e ninguém percebe", o descarte grita um
`log.error` no JSON local — que é justamente o que sobra quando o Sentry cala.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import structlog
from django.core.exceptions import ImproperlyConfigured
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from core.logging_middleware import safe_path

log = structlog.get_logger("sentry")

# PII do domínio (§ LGPD) somado ao denylist do SDK (que só conhece senha/token/cookie). Chaves em
# pt e en porque o payload atravessa fronteira: o funil web manda `cpf`, os serializers `phone`,
# o Asaas devolve `pixAddressKey`. O EventScrubber casa a chave em minúsculas.
PII_DENYLIST = [
    "cpf",
    "rg",
    "cnh",
    "phone",
    "telefone",
    "celular",
    "whatsapp",
    "email",
    "e_mail",
    "pix",
    "pix_key",
    "pixaddresskey",
    "chave_pix",
    "otp",
    "otp_code",
    "codigo",
    "birth_date",
    "nascimento",
    "mother_name",
    "nome_mae",
    "address",
    "endereco",
    "cep",
    "zipcode",
]

DENYLIST = list(DEFAULT_DENYLIST) + PII_DENYLIST

# ⚠️ O `EventScrubber` do SDK NÃO varre o evento inteiro: ele cobre `request`, `extra`, `user`,
# `breadcrumbs`, `frames` e `spans` — e mais nada (ver `EventScrubber.scrub_event` no SDK 2.66).
# Fica de fora justamente `contexts` — o destino do `sentry_sdk.set_context("candidato", {...})`,
# que é COMO se anexa dado de domínio — e `tags`. Nesses dois a máscara por FORMA do `scrub_event`
# não salva: ela pega CPF/telefone porque têm formato, mas uma chave Pix é um e-mail ou uma string
# aleatória — só o NOME da chave a denuncia. Por isso o `_walk` abaixo também filtra por chave.
_DENYLIST_SET = frozenset(k.lower() for k in DENYLIST)

# A MESMA string que o SDK usa no lugar do valor sensível (`SENSITIVE_DATA_SUBSTITUTE`), de forma
# que o painel não distinga o que foi filtrado por ele do que foi filtrado por nós.
#
# ⚠️ String pura, e NÃO o `AnnotatedValue` do SDK, por um motivo que só aparece em produção: o
# `serialize()` do cliente roda ANTES do `before_send` (client.py, SDK 2.66) — é ele quem traduz
# `AnnotatedValue` em `[Filtered]` + `_meta`. Um `AnnotatedValue` criado AQUI já perdeu esse trem
# e chega cru no `json.dumps` do envelope: `TypeError: Object of type AnnotatedValue is not JSON
# serializable`, e o evento inteiro morre na saída. Fica a regra: dentro do `before_send`, só
# tipos JSON puros.
FILTERED = "[Filtered]"

# Corpo do request: valores aceitos pelo SDK. "never" é o nosso default (ver camada 2 no topo).
REQUEST_BODY_CHOICES = frozenset({"never", "small", "medium", "always"})

# ── Máscara de PII em TEXTO LIVRE ────────────────────────────────────────────────────────────
# Só o que é reconhecível SEM ambiguidade — mascarar "qualquer sequência de dígitos" cegaria o
# diagnóstico (id, status, valor, timestamp). Por isso os limites são justos:
#   • CPF formatado  123.456.789-01
#   • 11 dígitos exatos  → CPF cru ou telefone BR com DDD. NÃO colide com epoch (10 = segundos,
#     13 = milissegundos), que são os números longos que de fato aparecem nos nossos erros.
#   • 12–13 dígitos começando em 55 → telefone BR com código do país (5511999990001). Epoch em ms
#     hoje começa em 17, então não entra aqui.
# Máscara `***XX` (últimos 2 dígitos) = a MESMA do `_scrub_pii` do settings — um evento no Sentry
# e a linha no log JSON ficam comparáveis a olho.
_CPF_FORMATTED = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_PHONE_BR_DDI = re.compile(r"(?<!\d)55\d{10,11}(?!\d)")
_ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")

_MAX_DEPTH = 20


def _mask(match: re.Match[str]) -> str:
    return f"***{match.group(0)[-2:]}"


def mask_pii_text(text: str) -> str:
    """Mascara CPF/telefone soltos numa string. Ordem importa: o formatado sai primeiro (senão o
    `\\d{11}` não casaria com ele de todo jeito, mas o DDI de 12–13 tem que sair antes do de 11
    pra não sobrar dígito órfão)."""
    text = _CPF_FORMATTED.sub(_mask, text)
    text = _PHONE_BR_DDI.sub(_mask, text)
    return _ELEVEN_DIGITS.sub(_mask, text)


def redact_media_url(url: str) -> str:
    """`/media/<prefixo>/<token>.<ext>` → o token É a credencial do arquivo (G1/#31), então some
    com ele. Reusa o `safe_path` do logging_middleware (uma fonte só), mas aqui a entrada é a URL
    ABSOLUTA que o Sentry monta — recorta a partir do `/media/` e preserva host e query-string."""
    idx = url.find("/media/")
    if idx == -1:
        return url
    head, rest = url[:idx], url[idx:]
    path, sep, query = rest.partition("?")
    return f"{head}{safe_path(path)}{sep}{query}"


def _walk(value: Any, depth: int = 0) -> Any:
    """Uma passada só, duas regras: valor sob CHAVE da denylist vira `[Filtered]`; toda STRING
    passa pela máscara por FORMA. As chaves em si nunca mudam — são estruturais pro Sentry
    (`exception`, `values`, `stacktrace`) e mexer nelas quebraria o parse do evento.

    Roda no evento INTEIRO (e não só em `contexts`/`tags`, os buracos conhecidos) de propósito:
    assim uma seção nova do SDK já nasce coberta, em vez de virar o próximo buraco. Nas seções que
    o scrubber nativo já tratou é idempotente — ele deixou a string `[Filtered]`, que segue igual.
    """
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return mask_pii_text(value)
    if isinstance(value, dict):
        return {
            k: FILTERED
            if isinstance(k, str) and k.lower() in _DENYLIST_SET
            else _walk(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_walk(v, depth + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk(v, depth + 1) for v in value)
    return value


def scrub_event(event: dict, hint: Any = None) -> dict | None:
    """`before_send`/`before_send_transaction`. Devolve o evento mascarado, ou `None` (descarta) se
    o scrub falhar — fail-closed, ver docstring do módulo."""
    try:
        scrubbed = _walk(event)
        request = scrubbed.get("request")
        if isinstance(request, dict) and isinstance(request.get("url"), str):
            request["url"] = redact_media_url(request["url"])
        return scrubbed
    except Exception:
        # Sem `raise`: exceção aqui dentro do SDK viraria outro evento → laço. Loga e engole.
        log.error("sentry_scrub_failed", event_id=str(event.get("event_id", ""))[:32])
        return None


def git_sha(base_dir: Path | str) -> str:
    """SHA do HEAD do checkout, ou "" se não der pra saber.

    Serve de default do `SENTRY_RELEASE` — e é EXATO aqui por causa de como o deploy funciona: o
    `deploy.yml` faz `git reset --hard <sha que passou no CI>` em `/opt/backend-supletivo`, então o
    HEAD **é** a release rodando, sem ninguém ter que lembrar de atualizar um .env a cada deploy.
    Sem isso o painel joga todo erro num balde só, e "isso começou em qual deploy?" — a primeira
    pergunta de todo incidente — vira arqueologia de log.

    Best-effort por toda parte: `git` ausente, `.git` ilegível pelo usuário do serviço, timeout →
    devolve "" e o Sentry só fica sem release. Nunca derruba o boot. Roda UMA vez por processo (no
    import do settings) e só quando há DSN — ver a chamada em `core/settings.py`.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def init_sentry(
    *,
    dsn: str,
    environment: str,
    release: str = "",
    traces_sample_rate: float = 0.0,
    request_body: str = "never",
) -> bool:
    """Liga o SDK. Sem DSN não faz nada e devolve False (dev/CI seguem sem observabilidade remota).

    Config inválida derruba o boot (`ImproperlyConfigured`, padrão do `core/environment.py`): um
    sample-rate fora de 0–1 é aceito calado pelo SDK e o efeito só aparece semanas depois na conta.
    """
    if not dsn:
        return False

    if not 0.0 <= traces_sample_rate <= 1.0:
        raise ImproperlyConfigured(
            f"SENTRY_TRACES_SAMPLE_RATE={traces_sample_rate!r} fora do intervalo 0.0–1.0."
        )
    if request_body not in REQUEST_BODY_CHOICES:
        allowed = ", ".join(sorted(REQUEST_BODY_CHOICES))
        raise ImproperlyConfigured(
            f"SENTRY_REQUEST_BODY={request_body!r} inválido; use um de: {allowed}."
        )

    import sentry_sdk

    # As integrações de Django e de `logging` sobem sozinhas (auto-enabling). É por essa segunda
    # que o worker do Django-Q chega aqui: o django-q2 não estoura a exceção pra fora, ele loga
    # ERROR — e a LoggingIntegration converte ERROR em evento. Sem ela, task quebrada = silêncio.
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        max_request_body_size=request_body,
        event_scrubber=EventScrubber(denylist=DENYLIST, recursive=True),
        before_send=scrub_event,
        before_send_transaction=scrub_event,
    )
    return True
