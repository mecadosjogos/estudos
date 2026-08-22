"""Casamento de termos do glossário contra texto corrido (PLANO.md). Uma
alternação regex só, compilada uma vez por chamada, cobre qualquer
quantidade de termos numa passada — sem isso, escanear página inteira de
livro contra centenas de termos vira `replace` por termo, lento e
repetitivo (PLANO.md: "isso precisa escalar").

Casamento é sempre feito sobre o texto **normalizado** (sem acento,
minúsculo) dos dois lados -- variante e alvo --, mas os spans devolvidos
são índices no texto ORIGINAL (`normalize_char_preserving` garante que os
dois têm o mesmo comprimento, span por span).
"""

import re
from dataclasses import dataclass

from .normalize import normalize_char_preserving


@dataclass
class VariantEntry:
    normalized: str
    term_id: int
    display: str  # a variante como cadastrada -- só para depuração/teste


@dataclass
class Match:
    start: int
    end: int
    term_id: int


def build_pattern(variants: list[VariantEntry]) -> re.Pattern | None:
    """Mais longas primeiro: entre "boa fé" e "boa fé objetiva", o
    casamento tem que preferir a mais específica quando as duas cabem no
    mesmo lugar do texto -- alternação regex tenta a ordem em que os
    ramos aparecem no padrão, então a ordenação aqui é o que decide."""
    if not variants:
        return None
    ordenadas = sorted(variants, key=lambda v: len(v.normalized), reverse=True)
    ramos = "|".join(re.escape(v.normalized) for v in ordenadas if v.normalized)
    if not ramos:
        return None
    return re.compile(rf"\b(?:{ramos})\b")


def find_matches(texto: str, variants: list[VariantEntry]) -> list[Match]:
    """Devolve os spans (no texto ORIGINAL, não normalizado) de cada
    variante casada, sem sobreposição -- `re.finditer` sobre uma
    alternação já devolve não-sobrepostos por conta própria, varrendo da
    esquerda pra direita."""
    pattern = build_pattern(variants)
    if pattern is None:
        return []

    normalizado = normalize_char_preserving(texto)
    by_normalized: dict[str, int] = {}
    for v in variants:
        # Em empate de comprimento, a primeira variante cadastrada vence
        # -- não deveria haver duas variantes idênticas de termos
        # diferentes (alias é único no banco), então isto só desempata
        # duplicata dentro da mesma lista em memória.
        by_normalized.setdefault(v.normalized, v.term_id)

    matches = []
    for m in pattern.finditer(normalizado):
        term_id = by_normalized.get(m.group(0))
        if term_id is None:
            continue
        matches.append(Match(start=m.start(), end=m.end(), term_id=term_id))
    return matches
