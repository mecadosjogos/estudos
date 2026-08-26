"""Rede de conceitos: grafo livre (não hierárquico) de Termos e Assuntos,
conectados por coocorrência textual -- nunca por IA. Decisão registrada em
PLANO.md ("Decisões fechadas"): pedir pra IA comparar cada termo contra o
glossário inteiro tem custo O(n²) que cresce sem controle conforme o
glossário cresce. Coocorrência é query/script determinístico sobre dados
que já existem, recalculado sob demanda a cada request -- mesmo espírito
de `library/coverage.py` ("recalculado sob demanda, nunca guardado").

Três escopos, mesma mecânica -- só muda a unidade de agrupamento:
- "bloco": um EditedBlock (só Termo<->Termo -- Assunto não tem posição
  dentro do texto, só liga a aula inteira via LessonAssunto)
- "aula": uma Lesson inteira (Termo<->Termo, Assunto<->Assunto,
  Termo<->Assunto)
- "materia": um Subject inteiro (mesmas três, unidade maior)

O cálculo em si (`build_edges`, `discrimination_edges`, `build_nodes`) é
todo função pura -- recebe listas já buscadas, sem sessão/query dentro,
igual `coverage.py`. Só `graph_json_for_lessons`, no fim do arquivo, toca
o banco: orquestra os SELECTs batched e chama as funções puras acima.
"""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..glossary.index import load_active_variants
from ..glossary.matcher import VariantEntry, find_matches
from ..glossary.normalize import normalize_char_preserving
from ..models import Assunto, AssuntoCobertura, CardProposal, Definition, EditedBlock, Lesson, LessonAssunto, Term


@dataclass
class GraphNode:
    id: str  # "term:12" ou "assunto:7" -- prefixo evita colisão de PK entre as duas tabelas
    tipo: str  # "term" | "assunto"
    label: str
    subject_ids: list[int] = field(default_factory=list)


@dataclass
class GraphEdge:
    a: str
    b: str
    peso: int
    origem: str = "cooccorrencia"  # "cooccorrencia" | "discriminacao"
    rotulo: str | None = None


def _node_id(tipo: str, id_: int) -> str:
    return f"{tipo}:{id_}"


def block_term_sets(blocks: list[EditedBlock], variants: list[VariantEntry]) -> dict[int, set[int]]:
    """term_ids que aparecem em cada bloco -- find_matches roda uma vez por
    bloco, reaproveitando o mesmo mecanismo que já destaca termo em
    prosa (glossary/matcher.py)."""
    return {block.id: {m.term_id for m in find_matches(block.texto, variants)} for block in blocks}


def build_edges(
    escopo: str,
    blocks: list[EditedBlock],
    lesson_assunto_pairs: list[tuple[int, int]],  # (lesson_id, assunto_id), já filtrado status="aceito"
    lesson_subject: dict[int, int],  # lesson_id -> subject_id
    variants: list[VariantEntry],
) -> list[GraphEdge]:
    if escopo not in ("bloco", "aula", "materia"):
        raise ValueError(f"escopo inválido: {escopo!r}")

    block_terms = block_term_sets(blocks, variants)

    groups_terms: dict[int, set[int]] = defaultdict(set)
    groups_assuntos: dict[int, set[int]] = defaultdict(set)

    if escopo == "bloco":
        for block in blocks:
            groups_terms[block.id] |= block_terms[block.id]
    elif escopo == "aula":
        for block in blocks:
            groups_terms[block.lesson_id] |= block_terms[block.id]
        for lesson_id, assunto_id in lesson_assunto_pairs:
            groups_assuntos[lesson_id].add(assunto_id)
    else:  # "materia"
        for block in blocks:
            subject_id = lesson_subject.get(block.lesson_id)
            if subject_id is not None:
                groups_terms[subject_id] |= block_terms[block.id]
        for lesson_id, assunto_id in lesson_assunto_pairs:
            subject_id = lesson_subject.get(lesson_id)
            if subject_id is not None:
                groups_assuntos[subject_id].add(assunto_id)

    peso: dict[tuple[str, str], int] = defaultdict(int)

    def _bump(id_a: str, id_b: str) -> None:
        key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
        peso[key] += 1

    for term_ids in groups_terms.values():
        for a, b in combinations(sorted(term_ids), 2):
            _bump(_node_id("term", a), _node_id("term", b))

    if escopo != "bloco":
        for group_key, assunto_ids in groups_assuntos.items():
            for a, b in combinations(sorted(assunto_ids), 2):
                _bump(_node_id("assunto", a), _node_id("assunto", b))
            for term_id in groups_terms.get(group_key, set()):
                for assunto_id in assunto_ids:
                    _bump(_node_id("term", term_id), _node_id("assunto", assunto_id))

    return [GraphEdge(a=a, b=b, peso=p) for (a, b), p in peso.items()]


def discrimination_edges(card_proposals: list[CardProposal], variants: list[VariantEntry]) -> list[GraphEdge]:
    """Reaproveita os cards de discriminação (fase 8b, já implementado) como
    aresta de alta precisão: o professor comparou os dois termos na fala,
    então o par já veio pronto de uma passada de IA que ia rodar de
    qualquer jeito -- custo zero adicional. `termo_a`/`termo_b` são texto
    livre no card, então casar contra o glossário com a mesma técnica que
    `glossary/mermaid.py::_term_lookup` usa pra rótulo de nó do Mermaid.
    Par que não resolve pra um Term ativo (ainda não é verbete aceito, ou
    a IA errou a grafia) é descartado -- mesmo comportamento que
    `mermaid.py` já tem hoje."""
    lookup: dict[str, int] = {}
    for variant in variants:
        lookup.setdefault(variant.normalized, variant.term_id)

    edges = []
    for card in card_proposals:
        if card.tipo != "discriminacao" or card.status != "aceito":
            continue
        if not card.termo_a or not card.termo_b:
            continue
        term_id_a = lookup.get(normalize_char_preserving(card.termo_a))
        term_id_b = lookup.get(normalize_char_preserving(card.termo_b))
        if term_id_a is None or term_id_b is None or term_id_a == term_id_b:
            continue
        a, b = _node_id("term", term_id_a), _node_id("term", term_id_b)
        if a > b:
            a, b = b, a
        edges.append(GraphEdge(a=a, b=b, peso=1, origem="discriminacao", rotulo=card.eixo_distincao))
    return edges


def node_ids_in_edges(edges: list[GraphEdge]) -> set[str]:
    ids: set[str] = set()
    for edge in edges:
        ids.add(edge.a)
        ids.add(edge.b)
    return ids


def build_nodes(
    node_ids: set[str],
    terms: list[Term],
    assuntos: list[Assunto],
    term_subject_rows: list[tuple[int, int]],  # (term_id, subject_id)
    assunto_subject_rows: list[tuple[int, int]],  # (assunto_id, subject_id)
) -> list[GraphNode]:
    """Monta os nós exibíveis a partir dos IDs que sobraram nas arestas.
    `subject_ids` alimenta a cor do nó no template: 1 matéria = cor
    daquela matéria, 2+ = cor de destaque -- o sinal visual de "este
    conceito atravessa disciplinas" que motivou a feature."""
    terms_by_id = {t.id: t for t in terms}
    assuntos_by_id = {a.id: a for a in assuntos}

    subject_ids_by_node: dict[str, set[int]] = defaultdict(set)
    for term_id, subject_id in term_subject_rows:
        subject_ids_by_node[_node_id("term", term_id)].add(subject_id)
    for assunto_id, subject_id in assunto_subject_rows:
        subject_ids_by_node[_node_id("assunto", assunto_id)].add(subject_id)

    nodes = []
    for node_id in node_ids:
        tipo, raw_id = node_id.split(":", 1)
        raw_id = int(raw_id)
        if tipo == "term":
            term = terms_by_id.get(raw_id)
            if term is None:
                continue
            label = term.rotulo
        else:
            assunto = assuntos_by_id.get(raw_id)
            if assunto is None:
                continue
            label = assunto.titulo
        nodes.append(
            GraphNode(id=node_id, tipo=tipo, label=label, subject_ids=sorted(subject_ids_by_node.get(node_id, set())))
        )
    return nodes


def term_subject_ids(session: Session, term_ids: set[int], variants: list[VariantEntry]) -> dict[int, set[int]]:
    """Em que matérias um termo aparece de verdade -- não via `Definition`
    (curadoria rara: só existe quando a IA capturou um ato definitório
    explícito), mas pelo mesmo `find_matches` que monta o resto da rede.
    Sem isso, um termo podia conectar dentro do grafo de uma matéria sem
    nunca ter ganhado uma `Definition` formal ali, e a cor de "conceito-
    ponte" nunca acendia onde mais importava. Varre todo `EditedBlock` do
    curso (poucos milhares, barato -- mesmo raciocínio de
    `glossary/index.py`) só pra achar em que matéria cada termo do grafo
    atual aparece, não pra recontar coocorrência."""
    if not term_ids:
        return {}

    all_blocks = session.scalars(select(EditedBlock).where(EditedBlock.orfao_em.is_(None))).all()
    lesson_ids = {b.lesson_id for b in all_blocks}
    lesson_subject = dict(session.execute(select(Lesson.id, Lesson.subject_id).where(Lesson.id.in_(lesson_ids))).all())

    result: dict[int, set[int]] = defaultdict(set)
    for block in all_blocks:
        subject_id = lesson_subject.get(block.lesson_id)
        if subject_id is None:
            continue
        matched = {m.term_id for m in find_matches(block.texto, variants)}
        for term_id in matched & term_ids:
            result[term_id].add(subject_id)
    return result


def graph_to_json(nodes: list[GraphNode], edges: list[GraphEdge]) -> str:
    return json.dumps({"nodes": [asdict(n) for n in nodes], "edges": [asdict(e) for e in edges]})


def graph_json_for_lessons(session: Session, escopo: str, lesson_ids: list[int]) -> str:
    """Orquestra as queries batched + o cálculo puro acima, pra rota não
    repetir a mesma sequência de SELECTs em `subjects.py` e `lessons.py`.
    Chamada com `lesson_ids` de uma matéria inteira (escopo="materia") ou
    de uma única aula (escopo="aula"/"bloco")."""
    if not lesson_ids:
        return graph_to_json([], [])

    variants = load_active_variants(session)

    blocks = session.scalars(
        select(EditedBlock).where(EditedBlock.lesson_id.in_(lesson_ids), EditedBlock.orfao_em.is_(None))
    ).all()

    lesson_assunto_pairs = list(
        session.execute(
            select(LessonAssunto.lesson_id, LessonAssunto.assunto_id).where(
                LessonAssunto.lesson_id.in_(lesson_ids), LessonAssunto.status == "aceito"
            )
        )
    )

    lesson_subject = dict(session.execute(select(Lesson.id, Lesson.subject_id).where(Lesson.id.in_(lesson_ids))).all())

    edges = build_edges(escopo, blocks, lesson_assunto_pairs, lesson_subject, variants)

    if escopo != "bloco":
        card_proposals = session.scalars(
            select(CardProposal).where(
                CardProposal.lesson_id.in_(lesson_ids),
                CardProposal.tipo == "discriminacao",
                CardProposal.status == "aceito",
            )
        ).all()
        edges += discrimination_edges(card_proposals, variants)

    node_ids = node_ids_in_edges(edges)
    term_ids = {int(nid.split(":", 1)[1]) for nid in node_ids if nid.startswith("term:")}
    assunto_ids = {int(nid.split(":", 1)[1]) for nid in node_ids if nid.startswith("assunto:")}

    terms = session.scalars(select(Term).where(Term.id.in_(term_ids))).all() if term_ids else []
    assuntos = session.scalars(select(Assunto).where(Assunto.id.in_(assunto_ids))).all() if assunto_ids else []

    term_subject_rows = (
        list(
            session.execute(
                select(Definition.term_id, Definition.subject_id)
                .where(
                    Definition.term_id.in_(term_ids),
                    Definition.status == "ativo",
                    Definition.subject_id.is_not(None),
                )
                .distinct()
            )
        )
        if term_ids
        else []
    )
    # Definition sozinha é sinal raro demais (curadoria manual, fase 6) --
    # soma o sinal barato de onde o termo realmente aparece no texto, pra
    # não perder matéria onde ele conecta mas nunca ganhou definição formal.
    term_subject_rows += [
        (term_id, subject_id)
        for term_id, subjects in term_subject_ids(session, term_ids, variants).items()
        for subject_id in subjects
    ]

    assunto_subject_rows = (
        list(
            session.execute(
                select(AssuntoCobertura.assunto_id, AssuntoCobertura.subject_id)
                .where(AssuntoCobertura.assunto_id.in_(assunto_ids))
                .distinct()
            )
        )
        if assunto_ids
        else []
    )

    nodes = build_nodes(node_ids, terms, assuntos, term_subject_rows, assunto_subject_rows)
    return graph_to_json(nodes, edges)
