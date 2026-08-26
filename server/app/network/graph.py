"""Rede de conceitos: grafo livre (não hierárquico) de Termos e Assuntos.
Nunca por IA nova (PLANO.md, "Decisões fechadas") -- fonte principal de
aresta Termo<->Termo é a taxonomia que a IA já desenha por aula
(`Lesson.mapa_mermaid`, fase 15/5b), parseada por
`glossary/mermaid.py::parse_taxonomy_edges`. Cada aula sozinha desenha
uma arvorezinha; a união de várias aulas pelo Term.id resolvido (não pelo
id interno do Mermaid, que só vale dentro de um diagrama) é o que vira
rede livre, não hierarquia forçada -- de graça, sem precisar de
coocorrência de texto.

Camadas sempre incluídas (baratas e precisas):
- taxonomia (Termo<->Termo, dirigida)
- discriminação (fase 8b, já implementado -- Termo<->Termo)
- assunto (Assunto<->Assunto e Termo<->Assunto via LessonAssunto)

Todas agrupadas **por aula individual** -- nunca fundem aulas diferentes
num grupo só, mesmo quando a chamada cobre a matéria inteira. É o que
evita a bola de pelo que a v1 (coocorrência bruta como fonte principal)
tinha nesse nível.

Camada opcional, desligada por padrão: coocorrência textual bruta
(`network/cooccurrence.py`) -- pra quem quiser ver também o que apareceu
perto no texto, sem estrutura desenhada.

O cálculo em si é todo função pura -- recebe listas já buscadas, sem
sessão/query dentro, igual `library/coverage.py` ("recalculado sob
demanda, nunca guardado"). `build_rede_json` (todas as camadas, com
filtro client-side na legenda) e `build_taxonomia_json` (card separado, só
a hierarquia, sem filtro nenhum) são os dois pontos que tocam o banco:
orquestram os SELECTs batched e chamam as funções puras acima.
"""

import json
from collections import defaultdict
from dataclasses import asdict
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..glossary.index import load_active_variants
from ..glossary.matcher import VariantEntry, find_matches
from ..glossary.mermaid import link_mermaid_nodes_to_glossary, merge_taxonomy_diagrams, parse_taxonomy_edges
from ..glossary.normalize import normalize_char_preserving
from ..models import Assunto, AssuntoCobertura, CardProposal, Definition, EditedBlock, Lesson, LessonAssunto, Term
from .cooccurrence import block_term_sets, cooccurrence_edges
from .types import GraphEdge, GraphNode, node_id


def taxonomy_edges(session: Session, lessons: list[Lesson]) -> list[GraphEdge]:
    """Une o mapa de taxonomia de cada aula pelo Term.id resolvido. Peso =
    em quantas aulas aquele par DIRIGIDO apareceu; lesson_ids acumula as
    aulas de origem (pro clique-na-aresta abrir a fonte). Direção é
    preservada como desenhada -- a->b de uma aula e b->a de outra viram
    duas arestas diferentes, não uma só (raro, e informativo se acontecer:
    mostra desenhos que discordam entre si)."""
    peso: dict[tuple[str, str], int] = defaultdict(int)
    rotulos: dict[tuple[str, str], str | None] = {}
    lesson_ids_by_pair: dict[tuple[str, str], set[int]] = defaultdict(set)

    for lesson in lessons:
        if not lesson.mapa_mermaid:
            continue
        for edge in parse_taxonomy_edges(lesson.mapa_mermaid, session):
            key = (node_id("term", edge.term_id_a), node_id("term", edge.term_id_b))
            peso[key] += 1
            lesson_ids_by_pair[key].add(lesson.id)
            if rotulos.get(key) is None and edge.rotulo:
                rotulos[key] = edge.rotulo

    return [
        GraphEdge(
            a=a,
            b=b,
            peso=p,
            origem="taxonomia",
            rotulo=rotulos.get((a, b)),
            lesson_ids=sorted(lesson_ids_by_pair[(a, b)]),
            direcionado=True,
        )
        for (a, b), p in peso.items()
    ]


def discrimination_edges(card_proposals: list[CardProposal], variants: list[VariantEntry]) -> list[GraphEdge]:
    """Reaproveita os cards de discriminação (fase 8b, já implementado) como
    aresta de alta precisão: o professor comparou os dois termos na fala,
    então o par já veio pronto de uma passada de IA que ia rodar de
    qualquer jeito -- custo zero adicional. `termo_a`/`termo_b` são texto
    livre no card, então casar contra o glossário com a mesma técnica que
    `glossary/mermaid.py` usa pro rótulo de nó do Mermaid. Par que não
    resolve pra um Term ativo é descartado -- mesmo comportamento que
    `mermaid.py` já tem."""
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
        a, b = node_id("term", term_id_a), node_id("term", term_id_b)
        if a > b:
            a, b = b, a
        edges.append(
            GraphEdge(a=a, b=b, peso=1, origem="discriminacao", rotulo=card.eixo_distincao, lesson_ids=[card.lesson_id])
        )
    return edges


def assunto_edges(
    blocks: list[EditedBlock],
    block_terms: dict[int, set[int]],
    lesson_assunto_pairs: list[tuple[int, int]],
) -> list[GraphEdge]:
    """Assunto<->Assunto e Termo<->Assunto, sempre agrupados por aula
    individual -- nunca funde os assuntos de aulas diferentes num grupo
    só, mesmo quando a chamada cobre a matéria inteira. Era esse
    agrupamento por matéria inteira que deixava o nível matéria denso
    demais na v1; aqui fica fixo no comportamento mais restrito desde o
    início."""
    terms_by_lesson: dict[int, set[int]] = defaultdict(set)
    for block in blocks:
        terms_by_lesson[block.lesson_id] |= block_terms.get(block.id, set())

    assuntos_by_lesson: dict[int, set[int]] = defaultdict(set)
    for lesson_id, assunto_id in lesson_assunto_pairs:
        assuntos_by_lesson[lesson_id].add(assunto_id)

    peso: dict[tuple[str, str], int] = defaultdict(int)
    lesson_ids_by_pair: dict[tuple[str, str], set[int]] = defaultdict(set)

    def _bump(id_a: str, id_b: str, lesson_id: int) -> None:
        key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
        peso[key] += 1
        lesson_ids_by_pair[key].add(lesson_id)

    for lesson_id, assunto_ids in assuntos_by_lesson.items():
        for a, b in combinations(sorted(assunto_ids), 2):
            _bump(node_id("assunto", a), node_id("assunto", b), lesson_id)
        for term_id in terms_by_lesson.get(lesson_id, set()):
            for assunto_id in assunto_ids:
                _bump(node_id("term", term_id), node_id("assunto", assunto_id), lesson_id)

    return [
        GraphEdge(a=a, b=b, peso=p, origem="assunto", lesson_ids=sorted(lesson_ids_by_pair[(a, b)]))
        for (a, b), p in peso.items()
    ]


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
        subject_ids_by_node[node_id("term", term_id)].add(subject_id)
    for assunto_id, subject_id in assunto_subject_rows:
        subject_ids_by_node[node_id("assunto", assunto_id)].add(subject_id)

    nodes = []
    for nid in node_ids:
        tipo, raw_id = nid.split(":", 1)
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
        nodes.append(GraphNode(id=nid, tipo=tipo, label=label, subject_ids=sorted(subject_ids_by_node.get(nid, set()))))
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


def _hydrate_nodes(session: Session, edges: list[GraphEdge], variants: list[VariantEntry]) -> list[GraphNode]:
    """A partir das arestas já calculadas, busca os Term/Assunto que
    sobraram e monta os nós exibíveis com cor por matéria. Compartilhado
    por `build_rede_json` (todas as camadas) e `build_taxonomia_json` (só
    taxonomia) -- a hidratação de nó é a mesma independente de quais
    camadas geraram a aresta."""
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

    return build_nodes(node_ids, terms, assuntos, term_subject_rows, assunto_subject_rows)


def build_rede_json(session: Session, lesson_ids: list[int], incluir_coocorrencia: bool = False) -> str:
    """Orquestra as queries batched + as camadas puras acima, pra rota não
    repetir a mesma sequência de SELECTs em `subjects.py` e `lessons.py`.
    Chamada com `lesson_ids` de uma matéria inteira ou de uma única aula
    -- não existe mais distinção de "escopo": taxonomia/discriminação/
    assunto sempre entram, agrupadas por aula individual internamente;
    `incluir_coocorrencia` liga a camada opcional de texto bruto."""
    if not lesson_ids:
        return graph_to_json([], [])

    variants = load_active_variants(session)
    lessons = session.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids))).all()

    blocks = session.scalars(
        select(EditedBlock).where(EditedBlock.lesson_id.in_(lesson_ids), EditedBlock.orfao_em.is_(None))
    ).all()
    block_terms = block_term_sets(blocks, variants)

    lesson_assunto_pairs = list(
        session.execute(
            select(LessonAssunto.lesson_id, LessonAssunto.assunto_id).where(
                LessonAssunto.lesson_id.in_(lesson_ids), LessonAssunto.status == "aceito"
            )
        )
    )

    edges = taxonomy_edges(session, lessons)
    edges += assunto_edges(blocks, block_terms, lesson_assunto_pairs)

    card_proposals = session.scalars(
        select(CardProposal).where(
            CardProposal.lesson_id.in_(lesson_ids),
            CardProposal.tipo == "discriminacao",
            CardProposal.status == "aceito",
        )
    ).all()
    edges += discrimination_edges(card_proposals, variants)

    if incluir_coocorrencia:
        edges += cooccurrence_edges(blocks, block_terms)

    nodes = _hydrate_nodes(session, edges, variants)
    return graph_to_json(nodes, edges)


def build_taxonomia_mermaid(session: Session, lesson_ids: list[int]) -> str:
    """Card "Taxonomia da matéria", separado da "Rede de conceitos"
    (decisão do usuário): só a hierarquia, renderizada com o mesmo
    mermaid.js do mapa por aula (fase 15) -- não com vis-network. Um
    grafo em layout de força não lembra em nada a árvore que a IA
    desenhou; o dagre do próprio Mermaid é que sabe desenhar hierarquia, e
    reusar o mesmo motor visual do `/lessons/{id}/mapa` é o que faz esse
    card parecer com o mapa real em vez de outra coisa.

    Ao contrário de `taxonomy_edges`/`build_rede_json`, NÃO exige que os
    rótulos já sejam verbetes aprovados -- `merge_taxonomy_diagrams` funde
    pelo texto do rótulo em si, então a estrutura inteira aparece mesmo
    antes de o glossário estar em dia (só o `click` pro verbete depende de
    aprovação, igual ao mapa por aula)."""
    if not lesson_ids:
        return ""

    lessons = session.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids))).all()
    sources = [lesson.mapa_mermaid for lesson in lessons if lesson.mapa_mermaid]
    merged = merge_taxonomy_diagrams(sources)
    if not merged:
        return ""
    return link_mermaid_nodes_to_glossary(merged, session)
