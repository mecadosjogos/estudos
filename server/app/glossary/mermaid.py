"""Liga os nós do mapa de taxonomia (Mermaid) aos verbetes do glossário
(PLANO.md, fase 15: "com os nós ligados aos verbetes do glossário") e funde
o mapa de várias aulas numa árvore só, pro card "Taxonomia da matéria"
(PLANO.md, 5b -- a "Rede de conceitos" que vivia ao lado desse card foi
removida por não servir pro estudo real; ver "Decisões fechadas").

Não é um parser de gramática Mermaid completo -- reconhece só o padrão
comum de definição de nó num flowchart (`Id[Rótulo]`, `Id(Rótulo)`,
`Id{Rótulo}`, `Id([Rótulo])`, `Id[[Rótulo]]` etc.) via regex, o bastante
pra achar "rótulo do nó" e casar contra o glossário; simplificação
deliberada dado que a IA sempre gera o mesmo estilo de flowchart simples
pedido no prompt."""

import json
import re
from collections import defaultdict

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


def build_taxonomy_tree(session: Session, mermaid_sources: list[str]) -> list[dict]:
    """Funde o Mermaid de várias aulas numa árvore só, deduplicando nó pelo
    RÓTULO normalizado -- o id interno do Mermaid só vale dentro de uma
    aula, o rótulo é o que persiste entre elas. Não exige que o rótulo já
    seja um verbete aprovado -- a estrutura em si é o produto aqui, `term_id`
    é só um bônus condicional. Usado pelo card "Taxonomia da matéria"
    (`build_taxonomia_tree_json` abaixo), renderizado com D3 (árvore
    colapsável, zoom/pan) -- Mermaid (tentativa anterior) é renderização
    estática, sem interação em tempo de execução; D3 é a ferramenta certa
    pra árvore hierárquica navegável.

    Simplificação deliberada: se o mesmo conceito aparece com PAIS
    diferentes em aulas diferentes (raro -- dois professores classificando
    o mesmo termo em ramos diferentes), só o primeiro pai encontrado vira
    aresta; uma árvore colapsável exige um pai por nó, mesmo espírito do
    resto do arquivo."""
    lookup = _term_lookup(session)

    children_by_label: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    label_text: dict[str, str] = {}
    has_parent: set[str] = set()

    for src in mermaid_sources:
        for label_a, label_b, rotulo in _iter_label_edges(src):
            normalized_a = normalize_char_preserving(label_a)
            normalized_b = normalize_char_preserving(label_b)
            label_text.setdefault(normalized_a, label_a)
            label_text.setdefault(normalized_b, label_b)
            if normalized_a == normalized_b or normalized_b in has_parent:
                continue
            children_by_label[normalized_a].append((normalized_b, rotulo))
            has_parent.add(normalized_b)

    def _build(normalized: str, edge_label: str | None) -> dict:
        return {
            "label": label_text[normalized],
            "term_id": lookup.get(normalized),
            "edge_label": edge_label,
            "children": [_build(child, r) for child, r in children_by_label.get(normalized, [])],
        }

    roots = [n for n in label_text if n not in has_parent]
    return [_build(root, None) for root in roots]


def build_taxonomia_tree_json(session: Session, lesson_ids: list[int]) -> str:
    """Orquestra o card "Taxonomia da matéria": busca o `mapa_mermaid` de
    cada aula em `lesson_ids` e funde numa árvore só (`build_taxonomy_tree`)."""
    if not lesson_ids:
        return "[]"

    lessons = session.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids))).all()
    sources = [lesson.mapa_mermaid for lesson in lessons if lesson.mapa_mermaid]
    if not sources:
        return "[]"
    return json.dumps(build_taxonomy_tree(session, sources))
