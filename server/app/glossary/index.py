"""Monta a lista de variantes ativas do glossário -- a entrada que
`matcher.py`/`render.py` precisam. Reconstruída a cada chamada em vez de
cacheada em memória (PLANO.md fala em manter o autômato "em memória,
reconstruído quando o glossário muda"): numa escala de centenas/poucos
milhares de termos, montar a lista e compilar a regex do zero a cada
request já é da ordem de milissegundos, e evita todo o risco de cache
desatualizado -- se a escala um dia doer de verdade, cachear com
invalidação por versão é a evolução natural deste módulo, não uma
reescrita.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Term, TermAlias
from .matcher import VariantEntry
from .normalize import normalize_char_preserving


def load_active_variants(session: Session) -> list[VariantEntry]:
    """Só termos com `destacar=True` entram -- "botão por verbete pra
    parar de destacar" (PLANO.md) é filtrar aqui, não apagar nada. Cada
    termo contribui sua própria grafia (`rotulo`) como uma variante
    implícita, além de toda `TermAlias` cadastrada -- sem isso, a grafia
    canônica só casaria se também estivesse duplicada como alias."""
    terms = session.scalars(select(Term).where(Term.destacar.is_(True))).all()
    if not terms:
        return []

    aliases_by_term: dict[int, list[str]] = {}
    for alias in session.scalars(
        select(TermAlias).where(TermAlias.term_id.in_([t.id for t in terms]))
    ):
        aliases_by_term.setdefault(alias.term_id, []).append(alias.alias)

    variants: list[VariantEntry] = []
    seen_normalized: set[str] = set()
    for term in terms:
        candidatos = [term.rotulo] + aliases_by_term.get(term.id, [])
        for display in candidatos:
            normalized = normalize_char_preserving(display)
            if not normalized or normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            variants.append(VariantEntry(normalized=normalized, term_id=term.id, display=display))
    return variants
