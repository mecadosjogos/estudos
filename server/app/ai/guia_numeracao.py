"""Numeração hierárquica e índice do guia de uma aula de consolidação
(PLANO.md, "Aula de consolidação"): `##` = 8, `###` = 8.1, `####` = 8.1a.

Gerada por código a cada renderização, nunca escrita pela IA -- a skill
/consolidar-guia escreve só os títulos, sem número. Numeração pela
posição, então editar uma seção renumera sozinho sem nada guardado pra
dessincronizar. `GuiaSecao.corpo` continua sem número (narração e pacote
de dissertativas leem o corpo cru); o número só entra na tela e no cache
`guia_md`.

Âncoras: `secao-8` é o contrato que já existe (dissertativas apontam pra
seção pelo número inteiro); `secao-8-1` e `secao-8-1a` descem daí.
`#####` em diante fica sem número -- três níveis bastam para localizar.
"""

import re
from typing import NamedTuple

_FENCE_RE = re.compile(r"^ *(```|~~~)")
_SUB_RE = re.compile(r"^(#{3,4})[ \t]+(.+?)[ \t#]*$")


class SecaoNumerada(NamedTuple):
    numero: int
    titulo: str
    corpo: str  # corpo com `###`/`####` numerados e ancorados
    indice: list[dict]  # filhos da seção no índice: [{numero, titulo, anchor, filhos}]


def letra(n: int) -> str:
    """1 -> a, 26 -> z, 27 -> aa (nunca deve passar de z, mas não quebra)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("a") + r) + s
    return s


def ancora(numero: str) -> str:
    return "secao-" + numero.replace(".", "-")


def numerar_secao(numero: int, titulo: str, corpo: str, *, com_ancora: bool = True) -> SecaoNumerada:
    """`com_ancora=False` pro cache `guia_md` (download/PDF), onde o
    `{#id}` do attr_list seria só ruído."""
    linhas = []
    filhos: list[dict] = []
    sub = 0
    conceito = 0
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
        if nivel == 3:
            sub += 1
            conceito = 0
            num = f"{numero}.{sub}"
            filhos.append({"numero": num, "titulo": texto, "anchor": ancora(num), "filhos": []})
        else:
            conceito += 1
            # `####` antes de qualquer `###` na seção: pendura direto na seção (8a).
            num = f"{numero}.{sub}{letra(conceito)}" if sub else f"{numero}{letra(conceito)}"
            no = {"numero": num, "titulo": texto, "anchor": ancora(num), "filhos": []}
            (filhos[-1]["filhos"] if sub else filhos).append(no)
        sufixo = f" {{#{ancora(num)}}}" if com_ancora else ""
        linhas.append(f"{m.group(1)} {num} {texto}{sufixo}")
    return SecaoNumerada(numero, titulo, "\n".join(linhas), filhos)


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
