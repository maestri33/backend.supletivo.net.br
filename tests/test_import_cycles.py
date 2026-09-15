"""Guarda contra ciclo de import entre módulos internos.

Ciclo de import não quebra o boot enquanto alguém esconder o `import` dentro de uma função — e foi
assim que `lead.service ↔ lead.checkout_links` e `hub ↔ promoter ↔ enrollment ↔ student` viveram
escondidos. O custo aparece depois: ninguém sabe quais imports locais são lazy-load proposital
(insightface/PIL pesam ~266ms no boot) e quais são gambiarra pra furar ciclo.

Este teste enxerga os DOIS: monta o grafo com imports de topo E de dentro de função, e falha se
existir componente fortemente conexo > 1.
"""

from __future__ import annotations

import ast
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _modname(p: pathlib.Path) -> str:
    return str(p.relative_to(_ROOT))[:-3].replace("/", ".").removesuffix(".__init__")


def _source_files() -> list[pathlib.Path]:
    return [
        p
        for p in _ROOT.rglob("*.py")
        if ".venv" not in p.parts
        and "tests" not in p.parts
        and "migrations" not in p.parts
    ]


def _import_graph() -> dict[str, set[str]]:
    files = _source_files()
    internal = {_modname(p) for p in files}

    def resolve(name: str) -> str | None:
        while name:
            if name in internal:
                return name
            name = name.rpartition(".")[0]
        return None

    graph: dict[str, set[str]] = {m: set() for m in internal}
    for p in files:
        me = _modname(p)
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"), str(p))):
            targets = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                # `from X import Y` pode importar o MÓDULO X.Y, não só um nome dentro de X
                targets = [
                    resolve(f"{node.module}.{a.name}") or resolve(node.module)
                    for a in node.names
                ]
            elif isinstance(node, ast.Import):
                targets = [resolve(a.name) for a in node.names]
            graph[me].update(t for t in targets if t and t != me)
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan: componentes fortemente conexos com mais de um módulo."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = [0]

    def strongconnect(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(10_000)
    try:
        for v in graph:
            if v not in index:
                strongconnect(v)
    finally:
        sys.setrecursionlimit(old_limit)
    return out


def test_sem_ciclo_de_import():
    cycles = _cycles(_import_graph())
    assert not cycles, "ciclo(s) de import: " + "; ".join(
        " -> ".join(c) for c in cycles
    )
