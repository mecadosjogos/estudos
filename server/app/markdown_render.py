"""Markdown -> HTML do guia de aula (e de qualquer texto que siga o mesmo
padrão de lista aninhada).

Python-Markdown só reconhece um subitem de lista quando ele está recuado
4 espaços (o `tab_length` dele). O guia -- escrito pela IA, editado à mão
no navegador, ou vindo de outro editor -- costuma recuar sublistas com 2
espaços, o padrão do CommonMark/GitHub. Sem normalizar, o subitem vira
irmão do item pai na mesma lista, e a hierarquia que a formatação devia
mostrar some ("Nacionalidade ativa/passiva" no mesmo nível de "Princípio
da nacionalidade", em vez de dentro dele).

Trocar `tab_length` pra 2 não serve: um parágrafo recuado 2 espaços
depois de uma linha em branco passaria a virar bloco de código.

Também transforma os parágrafos rotulados do guia ("Lei:", "Definição:",
"Exemplo:", "Atenção:", "Pergunta de aluno:", "Material da aula:") em
blocos visuais distintos, pra quem lê separar de relance o que é lei, o
que é definição, o que é exemplo e o que é explicação (sem rótulo). O
rótulo continua sendo texto puro no markdown -- quem lê o `guia_md` cru
(exportar .md, exercícios do guia, narração) não depende disso.
"""

from __future__ import annotations

import re

import markdown as markdown_lib

_LIST_ITEM_RE = re.compile(r"^( *)([-*+]|\d+[.)])( +)(.*)$")
_FENCE_RE = re.compile(r"^ *(```|~~~)")

_ROTULOS = [
    ("lei", r"Lei"),
    ("definicao", r"Defini[çc][ãa]o"),
    ("exemplo", r"Exemplo(?: [^:*\n]{1,30}?)?"),  # "Exemplo invertido:"
    ("atencao", r"Aten[çc][ãa]o"),
    ("aluno", r"Pergunta de aluno|Aluno"),
    ("material", r"Material da aula"),
]
_NOME = "|".join(f"(?P<{tipo}>{padrao})" for tipo, padrao in _ROTULOS)
# "Exemplo:", "**Exemplo:**" ou "**Exemplo**:", no começo da linha
_ROTULO_RE = re.compile(
    r"^(?:\*\*(?P<rb>" + _NOME.replace("?P<", "?P<b_") + r")(?::\*\*|\*\*:)"
    r"|(?P<rp>" + _NOME + r"):)[ \t]*"
)


def normalize_list_indent(text: str) -> str:
    """Recalcula o recuo de itens de lista por nível (4 espaços cada).

    O nível de um item vem do recuo relativo aos itens anteriores da mesma
    lista, não do número absoluto de espaços -- 2, 3 ou 4 espaços por nível
    dão o mesmo resultado. Linhas de continuação recuadas dentro de um item
    acompanham o nível do item. Blocos de código cercados ficam intactos.
    """
    out: list[str] = []
    stack: list[int] = []  # recuo original do marcador de cada nível aberto
    in_fence = False

    for line in text.replace("\r\n", "\n").split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        m = _LIST_ITEM_RE.match(line)
        if m:
            indent = len(m.group(1))
            while stack and indent < stack[-1]:
                stack.pop()
            if not stack or indent > stack[-1]:
                stack.append(indent)
            else:
                stack[-1] = indent
            level = len(stack) - 1
            out.append(" " * (4 * level) + m.group(2) + " " + m.group(4))
            continue

        if not line.strip():
            out.append(line)  # linha em branco não fecha a lista
            continue

        stripped = line.lstrip(" ")
        if stack and len(line) > len(stripped):
            out.append(" " * (4 * len(stack)) + stripped)
        else:
            stack.clear()
            out.append(line)

    return "\n".join(out)


def _tipo_rotulo(m: re.Match) -> str:
    for tipo, _ in _ROTULOS:
        if m.group(tipo) or m.group(f"b_{tipo}"):
            return tipo
    raise AssertionError("rótulo sem tipo")


def _continua_lista(lines: list[str], i: int) -> bool:
    line = lines[i]
    if _LIST_ITEM_RE.match(line) or line.startswith(" "):
        return True
    # linha em branco entre itens da mesma lista
    return not line.strip() and i + 1 < len(lines) and (
        bool(_LIST_ITEM_RE.match(lines[i + 1])) or lines[i + 1].startswith(" ")
    )


def wrap_labeled_blocks(text: str) -> str:
    """Envolve cada parágrafo rotulado num bloco `guia-bloco--<tipo>`, com o
    rótulo virando um selo. Se o parágrafo termina em ":" e uma lista vem
    logo depois ("Exemplo: são três casos:" seguido dos itens), a lista
    entra no mesmo bloco."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    in_fence = False
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        inicio_de_paragrafo = not out or not out[-1].strip()
        m = _ROTULO_RE.match(line) if inicio_de_paragrafo and not in_fence else None
        if not m:
            out.append(line)
            i += 1
            continue

        rotulo = (m.group("rb") or m.group("rp")).strip()
        bloco = [f'<span class="guia-rotulo">{rotulo}</span> ' + line[m.end():]]
        i += 1
        while i < len(lines) and lines[i].strip():  # resto do parágrafo
            bloco.append(lines[i])
            i += 1
        j = i + 1 if i < len(lines) else i  # pula a linha em branco
        if bloco[-1].rstrip().endswith(":") and j < len(lines) and _LIST_ITEM_RE.match(lines[j]):
            bloco.append("")
            i = j
            while i < len(lines) and _continua_lista(lines, i):
                bloco.append(lines[i])
                i += 1

        out.append(f'<div class="guia-bloco guia-bloco--{_tipo_rotulo(m)}" markdown="1">')
        out.append("")
        out.extend(bloco)
        out.append("")
        out.append("</div>")
    return "\n".join(out)


def render_markdown(text: str | None) -> str:
    md = wrap_labeled_blocks(normalize_list_indent(text or ""))
    return markdown_lib.markdown(md, extensions=["extra"])
