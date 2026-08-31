"""Interpreta o `guia_md` (markdown corrido escrito pela IA, ver ai/bridge.py) e deriva
os pedaços estruturados que o app persiste em banco (GuiaSecao/GuiaTopico, título,
árvore, trechos incompletos) -- zero chamada de IA extra, só parsing de texto. Ver
PLANO.md, "Guia estruturado", pro porquê da estrutura em banco existir mesmo com a IA
voltando a escrever um markdown só.

Nunca lança por desvio de formatação -- um guia mal formatado degrada pro fallback mais
simples (uma seção só, com o texto inteiro) em vez de perder conteúdo ou derrubar a
ingestão do resto da resposta da IA."""

import re
import unicodedata
from typing import NamedTuple

from pydantic import BaseModel, Field

TITULO_FALLBACK = "Aula sem título identificado"

_HEADER_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$")
_NUM_PREFIX_RE = re.compile(r"^\d+[.)]\s*")
_BULLET_RE = re.compile(r"^(\s*)[-*][ \t]+(.+?)\s*$")
_ORDERED_ITEM_RE = re.compile(r"^\s*\d+[.)][ \t]+(.+?)\s*$")


class GuiaArvoreNoOut(BaseModel):
    """Nó da árvore de conhecimento, derivado da lista aninhada em
    '## Árvore de conhecimento' dentro do `guia_md`."""

    rotulo: str
    filhos: list["GuiaArvoreNoOut"] = Field(default_factory=list)


class GuiaSecaoOut(BaseModel):
    """Uma seção do corpo do guia, derivada de um bloco '## <título>' do `guia_md`."""

    titulo: str
    corpo: str


class GuiaTopicoOut(BaseModel):
    """Item do sumário, derivado do bloco '## Sumário...' -- ou, na ausência desse
    bloco, um item por seção na mesma ordem (correspondência 1:1 padrão)."""

    titulo: str


class ParsedGuia(NamedTuple):
    titulo: str
    arvore: list[GuiaArvoreNoOut]
    secoes: list[GuiaSecaoOut]
    topicos: list[GuiaTopicoOut]
    trechos_incompletos: list[str]


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _classify(header_text: str) -> str:
    normalized = _strip_accents(header_text).strip().lower()
    if normalized.startswith("arvore de conhecimento"):
        return "arvore"
    if normalized.startswith("sumario"):
        return "sumario"
    if normalized.startswith("trechos incompletos"):
        return "trechos"
    return "secao"


def _parse_arvore(block_body: str) -> list[GuiaArvoreNoOut]:
    root: list[GuiaArvoreNoOut] = []
    stack: list[tuple[int, list[GuiaArvoreNoOut]]] = [(-1, root)]
    for line in block_body.split("\n"):
        m = _BULLET_RE.match(line.expandtabs())
        if not m:
            continue
        indent = len(m.group(1))
        rotulo = m.group(2).strip()
        if not rotulo:
            continue
        node = GuiaArvoreNoOut(rotulo=rotulo)
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((indent, node.filhos))
    return root


def _parse_topicos(block_body: str) -> list[GuiaTopicoOut]:
    topicos = []
    for line in block_body.split("\n"):
        text = line.strip()
        if not text:
            continue
        m = _BULLET_RE.match(line) or _ORDERED_ITEM_RE.match(line)
        titulo = m.group(m.lastindex).strip() if m else _NUM_PREFIX_RE.sub("", text).strip()
        if titulo:
            topicos.append(GuiaTopicoOut(titulo=titulo))
    return topicos


def _parse_trechos(block_body: str) -> list[str]:
    trechos = []
    for line in block_body.split("\n"):
        m = _BULLET_RE.match(line)
        if m and m.group(2).strip():
            trechos.append(m.group(2).strip())
    return trechos


def parse_guia_markdown(guia_md: str) -> ParsedGuia:
    text = (guia_md or "").replace("\r\n", "\n").strip()
    if not text:
        return ParsedGuia(TITULO_FALLBACK, [], [], [], [])

    lines = text.split("\n")
    titulo = TITULO_FALLBACK
    body_start = 0
    title_match = _TITLE_RE.match(lines[0].strip())
    if title_match:
        titulo = title_match.group(1).strip()
        body_start = 1
    body_text = "\n".join(lines[body_start:]).strip("\n")

    matches = list(_HEADER_RE.finditer(body_text))
    if not matches:
        secao = GuiaSecaoOut(titulo=titulo, corpo=body_text.strip())
        return ParsedGuia(titulo, [], [secao], [GuiaTopicoOut(titulo=titulo)], [])

    arvore: list[GuiaArvoreNoOut] = []
    secoes: list[GuiaSecaoOut] = []
    topicos: list[GuiaTopicoOut] = []
    trechos: list[str] = []
    has_sumario = False

    for i, m in enumerate(matches):
        header_text = m.group(1).strip()
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(body_text)
        block_body = body_text[block_start:block_end].strip("\n")

        kind = _classify(header_text)
        if kind == "arvore":
            arvore = _parse_arvore(block_body)
        elif kind == "sumario":
            topicos = _parse_topicos(block_body)
            has_sumario = True
        elif kind == "trechos":
            trechos = _parse_trechos(block_body)
        else:
            secao_titulo = _NUM_PREFIX_RE.sub("", header_text).strip() or header_text
            secoes.append(GuiaSecaoOut(titulo=secao_titulo, corpo=block_body.strip()))

    if not secoes:
        secoes = [GuiaSecaoOut(titulo=titulo, corpo=body_text.strip())]

    if not has_sumario:
        topicos = [GuiaTopicoOut(titulo=s.titulo) for s in secoes]

    return ParsedGuia(titulo, arvore, secoes, topicos, trechos)
