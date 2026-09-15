"""Parser/serializer do catálogo-base de notificações em Markdown (`notify/seed/templates.md`).

Formato (editável pelo Victor):

    [event:lead.paid]
    storytelling: false
    channels: whatsapp,email
    title: Parabéns!
    subject: Sua matrícula começou
    media_url:
    media_type:
    mail_template: default
    story_prompt:
    fires_on: Após pagamento confirmado (PIX ou cartão)
    source: users.roles.lead
    delay_minutes: 0
    active: true
    ~~~
    Parabéns, {nome}! 🎉 Seu pagamento foi confirmado e sua matrícula começou.
    Você deu um passo importante, {nome} — em breve enviamos os próximos passos.
    ~~~

- `[event:<slug>]` inicia um bloco; cabeçalho `chave: valor` (YAML-like, valores simples);
  `~~~` cerca o body (Markdown, multiline); próximo bloco ou EOF fecha.
- `#` no início de linha (fora do body) é comentário.
- Campos opcionais/vazios (`media_url:`, `story_prompt:`) viram None.
- `channels` é CSV; `delay_minutes` int; `storytelling`/`active` bool (true/false).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EVENT_HEADER_RE = re.compile(r"^\[event:([a-z][a-z0-9_.-]*)\]\s*$")
_FENCE = "~~~"
_BOOLS = {"true": True, "false": False, "yes": True, "no": False, "1": True, "0": False}

# campos escalares reconhecidos no cabeçalho (o resto é ignorado com warning pelo caller).
_SCALAR_STR = {
    "title",
    "subject",
    "media_url",
    "media_type",
    "mail_template",
    "fires_on",
    "source",
    "channels",
}
_BOOL_FIELDS = {"active", "is_tts"}
_INT_FIELDS = {"delay_minutes"}


@dataclass
class TemplateSpec:
    event: str
    body_md: str
    is_tts: bool = False
    channels: str = "whatsapp,email"
    title: str | None = None
    subject: str | None = None
    media_url: str | None = None
    media_type: str | None = None
    mail_template: str = "default"
    fires_on: str | None = None
    source: str | None = None
    delay_minutes: int = 0
    active: bool = True


def parse(text: str) -> list[TemplateSpec]:
    """Texto .md → lista de TemplateSpec (ordem do arquivo). Levanta ValueError se malformado."""
    specs: list[TemplateSpec] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _EVENT_HEADER_RE.match(line)
        if not m:
            i += 1  # comentário/linha solta fora de bloco — ignora
            continue
        event = m.group(1)
        i += 1
        header: dict[str, str] = {}
        # cabeçalho: linhas 'chave: valor' até a cerca `~~~`
        while i < n and lines[i].strip() != _FENCE:
            hl = lines[i]
            if hl.strip().startswith("#") or not hl.strip():
                i += 1
                continue
            if ":" not in hl:
                raise ValueError(f"linha sem 'chave: valor' no evento {event}: {hl!r}")
            k, v = hl.split(":", 1)
            header[k.strip()] = v.strip()
            i += 1
        if i >= n or lines[i].strip() != _FENCE:
            raise ValueError(f"body sem cerca '~~~' no evento {event}")
        i += 1  # abre o body
        body_lines: list[str] = []
        while i < n and lines[i].strip() != _FENCE:
            body_lines.append(lines[i])
            i += 1
        if i >= n:
            raise ValueError(f"body não fechado com '~~~' no evento {event}")
        i += 1  # fecha o body
        body = "\n".join(body_lines).strip("\n")
        specs.append(_spec_from_header(event, header, body))
    return specs


def _spec_from_header(event: str, header: dict[str, str], body: str) -> TemplateSpec:
    def _str(key: str) -> str | None:
        v = header.get(key)
        return v if v else None

    def _bool(key: str, default: bool) -> bool:
        v = header.get(key, "").strip().lower()
        if not v:
            return default
        if v in _BOOLS:
            return _BOOLS[v]
        raise ValueError(f"{key} inválido no evento {event}: {header.get(key)!r}")

    def _int(key: str, default: int) -> int:
        v = header.get(key, "").strip()
        if not v:
            return default
        try:
            return int(v)
        except ValueError as exc:
            raise ValueError(f"{key} inválido no evento {event}: {v!r}") from exc

    return TemplateSpec(
        event=event,
        body_md=body,
        is_tts=_bool("is_tts", False),
        channels=header.get("channels", "whatsapp,email").strip() or "whatsapp,email",
        title=_str("title"),
        subject=_str("subject"),
        media_url=_str("media_url"),
        media_type=_str("media_type"),
        mail_template=header.get("mail_template", "default").strip() or "default",
        fires_on=_str("fires_on"),
        source=_str("source"),
        delay_minutes=_int("delay_minutes", 0),
        active=_bool("active", True),
    )
