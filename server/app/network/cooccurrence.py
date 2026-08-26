"""Coocorrência textual bruta -- camada OPCIONAL da rede de conceitos,
desligada por padrão (PLANO.md, 5b v2). Dois termos "colidem" se
apareceram no mesmo `EditedBlock`; agrupamento é sempre por aula
individual, nunca funde aulas diferentes num grupo só -- nem aqui, nem
quando a chamada cobre a matéria inteira. Era o agrupamento por matéria
inteira que deixava esse nível impossível de visualizar na v1; a fonte
principal de aresta Termo<->Termo agora é a taxonomia
(`network/graph.py::taxonomy_edges`), isto aqui é só o complemento pra
quem quiser ver também o que apareceu perto no texto, sem estrutura
desenhada.
"""

from collections import defaultdict
from itertools import combinations

from ..glossary.matcher import VariantEntry, find_matches
from ..models import EditedBlock
from .types import GraphEdge, node_id


def block_term_sets(blocks: list[EditedBlock], variants: list[VariantEntry]) -> dict[int, set[int]]:
    """term_ids que aparecem em cada bloco -- find_matches roda uma vez por
    bloco, reaproveitando o mesmo mecanismo que já destaca termo em
    prosa (glossary/matcher.py). Usado tanto por esta camada opcional
    quanto por `graph.py::assunto_edges` (Termo<->Assunto precisa saber
    quais termos apareceram em cada aula, independente da coocorrência
    bruta estar ligada ou não)."""
    return {block.id: {m.term_id for m in find_matches(block.texto, variants)} for block in blocks}


def cooccurrence_edges(blocks: list[EditedBlock], block_terms: dict[int, set[int]]) -> list[GraphEdge]:
    """Termo<->Termo por proximidade textual, agrupado por aula individual.
    `block_terms` já vem calculado (evita rodar find_matches duas vezes
    quando `graph.py` também precisa dele pra `assunto_edges`)."""
    terms_by_lesson: dict[int, set[int]] = defaultdict(set)
    for block in blocks:
        terms_by_lesson[block.lesson_id] |= block_terms.get(block.id, set())

    peso: dict[tuple[str, str], int] = defaultdict(int)
    lesson_ids_by_pair: dict[tuple[str, str], set[int]] = defaultdict(set)

    for lesson_id, term_ids in terms_by_lesson.items():
        for a, b in combinations(sorted(term_ids), 2):
            id_a, id_b = node_id("term", a), node_id("term", b)
            key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
            peso[key] += 1
            lesson_ids_by_pair[key].add(lesson_id)

    return [
        GraphEdge(a=a, b=b, peso=p, origem="coocorrencia", lesson_ids=sorted(lesson_ids_by_pair[(a, b)]))
        for (a, b), p in peso.items()
    ]
