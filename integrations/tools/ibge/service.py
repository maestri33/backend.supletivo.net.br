"""IBGE — municípios oficiais (autocomplete da cidade da escola).

O protótipo é explícito: a cidade NÃO é texto livre. O autocomplete consulta a base do IBGE,
só aceita município existente e a UF é deduzida da própria resposta — nunca perguntada.

A lista muda pouquíssimo (5.570 municípios), então baixamos uma vez e guardamos em cache no
processo; se o IBGE estiver fora do ar, caímos no cache em disco. Sem egress, devolve vazio e
a tela deixa seguir com o que a pessoa escreveu (marcado para conferência).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
_CACHE_FILE = (
    Path(settings.BASE_DIR) / "integrations" / "tools" / "ibge" / "municipios.json"
)
_MEM: list[dict] | None = None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _uf_de(m: dict) -> str:
    """A UF vem por dois caminhos no JSON do IBGE — alguns municípios só têm o segundo."""
    uf = (((m.get("microrregiao") or {}).get("mesorregiao") or {}).get("UF") or {}).get(
        "sigla"
    )
    if uf:
        return uf
    ri = (m.get("regiao-imediata") or {}).get("regiao-intermediaria") or {}
    return ((ri.get("UF") or {}).get("sigla")) or ""


def _load() -> list[dict]:
    global _MEM
    if _MEM is not None:
        return _MEM
    if _CACHE_FILE.exists():
        try:
            _MEM = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            return _MEM
        except Exception:  # noqa: BLE001 — cache corrompido: tenta a rede
            pass
    try:
        r = httpx.get(_URL, timeout=12.0)
        r.raise_for_status()
        _MEM = [{"nome": m["nome"], "uf": _uf_de(m), "ibge": m["id"]} for m in r.json()]
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_MEM, ensure_ascii=False), encoding="utf-8")
        logger.info("ibge.municipios_baixados", total=len(_MEM))
    except Exception as exc:  # noqa: BLE001 — sem egress: o funil não pode travar por isto
        logger.warning("ibge.indisponivel", error=type(exc).__name__)
        _MEM = []
    return _MEM


def buscar(q: str, limite: int = 8) -> list[dict]:
    """Municípios que começam com `q` (e depois os que contêm), com a UF oficial junto."""
    termo = _norm(q).strip()
    if len(termo) < 2:
        return []
    dados = _load()
    comeca = [m for m in dados if _norm(m["nome"]).startswith(termo)]
    contem = [m for m in dados if termo in _norm(m["nome"]) and m not in comeca]
    return (comeca + contem)[:limite]


def existe(nome: str, uf: str | None = None) -> dict | None:
    """Confere se o município existe de verdade (o backend não aceita cidade inventada)."""
    alvo = _norm(nome)
    for m in _load():
        if _norm(m["nome"]) == alvo and (uf is None or m["uf"].upper() == uf.upper()):
            return m
    return None
