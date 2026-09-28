"""Numeração hierárquica e índice do guia de uma aula de consolidação
(PLANO.md, "Aula de consolidação"): numeração progressiva decimal, no
padrão da ABNT NBR 6024 -- `##` = 8, `###` = 8.1, `####` = 8.1.1,
`#####` = 8.1.1.1, `######` = 8.1.1.1.1 (cinco níveis, o máximo da norma
e o máximo de título que o markdown tem).

A profundidade é do conteúdo, não do formato: cada ramo desce quantos
níveis a matéria pede, e um título pendura no título mais próximo acima
dele que for mais raso -- pular nível (`#####` logo depois de `###`) não
gera número com zero, vira filho direto.

Gerada por código a cada renderização, nunca escrita pela IA -- a skill
/consolidar-guia escreve só os títulos, sem número. Numeração pela
posição, então editar uma seção renumera sozinho sem nada guardado pra
dessincronizar. `GuiaSecao.corpo` continua sem número (narração e pacote
de dissertativas leem o corpo cru); o número só entra na tela e no cache
`guia_md`.

Âncoras: `secao-8` é o contrato que já existe (dissertativas apontam pra
seção pelo número inteiro); `secao-8-1`, `secao-8-1-1` descem daí.
"""

import re
from typing import NamedTuple

_FENCE_RE = re.compile(r"^ *(```|~~~)")
_SUB_RE = re.compile(r"^(#{3,6})[ \t]+(.+?)[ \t#]*$")


class SecaoNumerada(NamedTuple):
    numero: int
    titulo: str
    corpo: str  # corpo com `###`..`######` numerados e ancorados
    indice: list[dict]  # filhos da seção no índice: [{numero, titulo, anchor, filhos}]


def ancora(numero: str) -> str:
    return "secao-" + numero.replace(".", "-")


def numerar_secao(numero: int, titulo: str, corpo: str, *, com_ancora: bool = True) -> SecaoNumerada:
    """`com_ancora=False` pro cache `guia_md` (download/PDF), onde o
    `{#id}` do attr_list seria só ruído."""
    linhas = []
    raiz: dict = {"numero": str(numero), "filhos": []}
    # (nível do título, nó) -- o topo é o pai do próximo título mais fundo.
    pilha: list[tuple[int, dict]] = [(2, raiz)]
    in_fence = False
    for line in corpo.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _SUB_RE.match(line)
        if not m:
            linhas.append(line)
            continue
        nivel = len(m.group(1))
        texto = m.group(2).strip()
        while pilha[-1][0] >= nivel:
            pilha.pop()
        pai = pilha[-1][1]
        num = f"{pai['numero']}.{len(pai['filhos']) + 1}"
        no = {"numero": num, "titulo": texto, "anchor": ancora(num), "filhos": []}
        pai["filhos"].append(no)
        pilha.append((nivel, no))
        sufixo = f" {{#{ancora(num)}}}" if com_ancora else ""
        linhas.append(f"{m.group(1)} {num} {texto}{sufixo}")
    return SecaoNumerada(numero, titulo, "\n".join(linhas), raiz["filhos"])


def numerar_consolidado(secoes: list[tuple[str, str]], *, com_ancora: bool = True) -> list[SecaoNumerada]:
    """`secoes` = [(titulo, corpo)] na ordem do guia; devolve cada uma
    numerada a partir de 1."""
    return [
        numerar_secao(i, titulo, corpo, com_ancora=com_ancora)
        for i, (titulo, corpo) in enumerate(secoes, start=1)
    ]


def indice_markdown(numeradas: list[SecaoNumerada]) -> str:
    """Índice aninhado em markdown (4 espaços por nível, mesmo motivo da
    árvore em guia_markdown.py) pro cache `guia_md`/PDF."""

    def _linhas(nos: list[dict], nivel: int) -> list[str]:
        out = []
        for no in nos:
            out.append("    " * nivel + f"- {no['numero']} {no['titulo']}")
            out.extend(_linhas(no["filhos"], nivel + 1))
        return out

    linhas = []
    for s in numeradas:
        linhas.append(f"- {s.numero} {s.titulo}")
        linhas.extend(_linhas(s.indice, 1))
    return "\n".join(linhas)
