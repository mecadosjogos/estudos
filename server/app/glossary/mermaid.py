"""Liga os nós do mapa de taxonomia (Mermaid) aos verbetes do glossário
(PLANO.md, fase 15: "com os nós ligados aos verbetes do glossário") e funde
o mapa de várias aulas num diagrama só, pro card "Taxonomia da matéria"
(PLANO.md, 5b -- a "Rede de conceitos" que vivia ao lado desse card foi
removida por não servir pro estudo real; ver "Decisões fechadas").

Não é um parser de gramática Mermaid completo -- reconhece só o padrão
comum de definição de nó num flowchart (`Id[Rótulo]`, `Id(Rótulo)`,
`Id{Rótulo}`, `Id([Rótulo])`, `Id[[Rótulo]]` etc.) via regex, o bastante
pra achar "rótulo do nó" e casar contra o glossário; simplificação
deliberada dado que a IA sempre gera o mesmo estilo de flowchart simples
pedido no prompt."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Lesson
from .index import load_active_variants
from .normalize import normalize_char_preserving

# Conteúdo do rótulo vem em dois sabores: entre aspas (`["Direito objetivo
# (positivo)"]`, o estilo que a IA sempre usa na prática -- confirmado
# olhando o mapa real de produção) ou sem aspas. Aspa é tratada primeiro e
# aceita QUALQUER caractere dentro, inclusive parêntese/colchete -- rótulo
# jurídico com parêntese explicativo é comum ("Normas jurídicas (códigos,
# leis)") e sem esse cuidado o `(` interno era lido como se abrisse um
# SEGUNDO nó, corrompendo o rótulo inteiro. Sem aspas cai no fallback
# antigo, que ainda exclui bracket/parêntese (não dá pra saber onde o
# rótulo termina sem eles).
_RE_MIOLO_ROTULO = r'\s*(?:"([^"]*)"|([^"\[\]\(\)\{\}]+?))\s*'

_NODE_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*(?:\[\[|\(\(|\[\(|\(\[|[\[\(\{])" + _RE_MIOLO_ROTULO + r"(?:\]\]|\)\)|\)\]|\[\)|[\]\)\}])",
)

# Mesmo padrão do _NODE_RE acima, mas sem a âncora em ^ -- usado só por
# parse_taxonomy_edges pra achar rótulo definido no meio da linha (`A -->
# B[Propriedade]` define B fora do início da linha).
_NODE_ANYWHERE_RE = re.compile(
    r"\b([A-Za-z0-9_]+)\s*(?:\[\[|\(\(|\[\(|\(\[|[\[\(\{])" + _RE_MIOLO_ROTULO + r"(?:\]\]|\)\)|\)\]|\[\)|[\]\)\}])",
)


def _rotulo_do_match(match: re.Match) -> str:
    """group(2) = conteúdo entre aspas, group(3) = sem aspas -- só um dos
    dois vem preenchido, dependendo de qual ramo de _RE_MIOLO_ROTULO casou."""
    return (match.group(2) if match.group(2) is not None else match.group(3) or "").strip()

_ARROW_TOKEN_RE = re.compile(r"-\.->|-\.-|==+>|===+|--+>|---+")
_ID_BEFORE_ARROW_RE = re.compile(
    r"([A-Za-z0-9_]+)\s*(?:\[\[[^\]]*\]\]|\(\([^)]*\)\)|\[[^\]]*\]|\([^)]*\)|\{[^}]*\})?\s*$"
)
_LABEL_AFTER_ARROW_RE = re.compile(r"^\s*\|([^|]*)\|")
_ID_AFTER_ARROW_RE = re.compile(r"^\s*([A-Za-z0-9_]+)")


def _term_lookup(session: Session) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for variant in load_active_variants(session):
        lookup.setdefault(variant.normalized, variant.term_id)
    return lookup


def link_mermaid_nodes_to_glossary(mermaid_src: str, session: Session) -> str:
    if not mermaid_src or not mermaid_src.strip():
        return mermaid_src

    lookup = _term_lookup(session)
    if not lookup:
        return mermaid_src

    click_lines = []
    seen_node_ids: set[str] = set()
    for line in mermaid_src.splitlines():
        match = _NODE_RE.match(line)
        if not match:
            continue
        node_id, label = match.group(1), _rotulo_do_match(match)
        if node_id in seen_node_ids:
            continue
        term_id = lookup.get(normalize_char_preserving(label))
        if term_id is None:
            continue
        seen_node_ids.add(node_id)
        click_lines.append(f'click {node_id} "/termos/{term_id}" "_self"')

    if not click_lines:
        return mermaid_src
    return mermaid_src.rstrip() + "\n" + "\n".join(click_lines) + "\n"


def _all_node_labels(mermaid_src: str) -> dict[str, str]:
    """Rótulo de nó em qualquer posição da linha, não só no início --
    diferente de `_NODE_RE` (usado pro `click` acima), que só reconhece
    definição de nó no começo da linha. Precisa ser mais permissivo aqui
    porque `A --> B[Propriedade]` define B no meio da linha, não só no
    começo."""
    labels: dict[str, str] = {}
    for line in mermaid_src.splitlines():
        for match in _NODE_ANYWHERE_RE.finditer(line):
            node_id, label = match.group(1), _rotulo_do_match(match)
            labels.setdefault(node_id, label)
    return labels


def _iter_label_edges(mermaid_src: str):
    """Gera (rótulo_a, rótulo_b, rótulo_da_seta) pra cada seta do Mermaid --
    usado por `merge_taxonomy_diagrams` abaixo. Não é parser de gramática
    Mermaid completa -- mesma simplificação deliberada do resto do
    arquivo: uma seta por ocorrência, sem suportar encadeamento tipo
    `A --> B --> C` como duas arestas (só a primeira seta da linha é
    capturada nesse caso)."""
    if not mermaid_src or not mermaid_src.strip():
        return

    labels = _all_node_labels(mermaid_src)

    for line in mermaid_src.splitlines():
        for arrow in _ARROW_TOKEN_RE.finditer(line):
            before_match = _ID_BEFORE_ARROW_RE.search(line[: arrow.start()])
            if before_match is None:
                continue

            after = line[arrow.end() :]
            label_match = _LABEL_AFTER_ARROW_RE.match(after)
            rotulo = None
            if label_match:
                texto = label_match.group(1).strip()
                rotulo = texto or None
                after = after[label_match.end() :]

            after_match = _ID_AFTER_ARROW_RE.match(after)
            if after_match is None:
                continue

            id_a, id_b = before_match.group(1), after_match.group(1)
            yield labels.get(id_a, id_a), labels.get(id_b, id_b), rotulo


def merge_taxonomy_diagrams(mermaid_sources: list[str]) -> str:
    """Funde o Mermaid de várias aulas num diagrama só, deduplicando nó
    pelo RÓTULO normalizado -- o id interno do Mermaid só vale dentro de
    uma aula, o rótulo é o que persiste entre elas. Não exige que o
    rótulo já seja um verbete aprovado -- a estrutura em si é o produto
    aqui, não um grafo de Term.id. Usado pelo card "Taxonomia da matéria"
    (`build_taxonomia_mermaid` abaixo), renderizado com o mesmo mermaid.js
    do mapa por aula (fase 15) -- forçar isso num layout de força
    (vis-network, tentativa anterior desta feature) não lembrava em nada a
    árvore que a IA desenhou; o dagre do próprio Mermaid é que sabe
    desenhar hierarquia."""
    id_by_normalized: dict[str, str] = {}
    label_by_id: dict[str, str] = {}
    edges_seen: set[tuple[str, str]] = set()
    lines: list[str] = []

    def _mermaid_id(label: str) -> str:
        normalized = normalize_char_preserving(label)
        if normalized not in id_by_normalized:
            id_by_normalized[normalized] = f"n{len(id_by_normalized)}"
            label_by_id[id_by_normalized[normalized]] = label
        return id_by_normalized[normalized]

    for src in mermaid_sources:
        for label_a, label_b, rotulo in _iter_label_edges(src):
            id_a, id_b = _mermaid_id(label_a), _mermaid_id(label_b)
            if id_a == id_b or (id_a, id_b) in edges_seen:
                continue
            edges_seen.add((id_a, id_b))
            label_a_escapada = label_by_id[id_a].replace('"', "'")
            label_b_escapada = label_by_id[id_b].replace('"', "'")
            seta = f'-->|"{rotulo}"|' if rotulo else "-->"
            lines.append(f'  {id_a}["{label_a_escapada}"] {seta} {id_b}["{label_b_escapada}"]')

    if not lines:
        return ""
    return "graph TD\n" + "\n".join(lines) + "\n"


def build_taxonomia_mermaid(session: Session, lesson_ids: list[int]) -> str:
    """Orquestra o card "Taxonomia da matéria": busca o `mapa_mermaid` de
    cada aula em `lesson_ids`, funde num diagrama só (`merge_taxonomy_
    diagrams`) e liga aos verbetes (`link_mermaid_nodes_to_glossary`) --
    mesmos dois passos que o mapa por aula já faz, só que sobre o texto
    fundido em vez do de uma aula só."""
    if not lesson_ids:
        return ""

    lessons = session.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids))).all()
    sources = [lesson.mapa_mermaid for lesson in lessons if lesson.mapa_mermaid]
    merged = merge_taxonomy_diagrams(sources)
    if not merged:
        return ""
    return link_mermaid_nodes_to_glossary(merged, session)
