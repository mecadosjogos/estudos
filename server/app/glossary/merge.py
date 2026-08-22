"""Ferramentas de correção do glossário (PLANO.md): fundir, separar,
achar-ou-criar por grafia. Mesmo padrão de `assuntos.py` (mesmo motivo:
a IA propõe "negócio jurídico" numa semana e "negócios jurídicos" noutra,
e sem essas ferramentas desde o início o glossário apodrece em dois
meses) -- reaproveita o mesmo `normalize_slug` pra casar grafia por
slug, então "Boa-fé" e "boa fé" caem no mesmo `Term` sem duplicar.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assuntos import normalize_slug
from ..models import Definition, FeynmanAttempt, Term, TermAlias, TermPin


def find_or_create_term(session: Session, rotulo: str) -> Term:
    slug = normalize_slug(rotulo)
    existing = session.scalar(select(Term).where(Term.slug == slug))
    if existing is not None:
        return existing
    term = Term(slug=slug, rotulo=rotulo.strip())
    session.add(term)
    session.flush()
    return term


def merge_terms(session: Session, source_id: int, target_id: int) -> None:
    """Migra definições, aliases e a própria grafia antiga (como alias
    novo) de `source` pra `target`, depois apaga `source` -- nada fica
    órfão (PLANO.md: "fundir move todas as definições e variantes para o
    termo que fica")."""
    if source_id == target_id:
        return
    source = session.get(Term, source_id)
    target = session.get(Term, target_id)
    if source is None or target is None:
        return

    # Reatribui pela relação (`.term`), não pela coluna crua (`.term_id`):
    # `Term.definitions`/`Term.aliases` têm cascade="all, delete-orphan", e
    # mexer só na coluna deixa o `source` achando, em memória, que ainda é
    # dono da linha -- o `session.delete(source)` lá embaixo cascateia e
    # tenta apagar algo que já devia ter virado do `target`.
    for definition in session.scalars(select(Definition).where(Definition.term_id == source_id)):
        definition.term = target

    existing_aliases = {a.alias for a in target.aliases}
    for alias in session.scalars(select(TermAlias).where(TermAlias.term_id == source_id)):
        if alias.alias in existing_aliases:
            session.delete(alias)
        else:
            alias.term = target
            existing_aliases.add(alias.alias)

    # A grafia antiga do termo fundido também precisa continuar casando
    # -- sem isso, "Culpa" apontando pra si mesma some do texto assim que
    # ela deixa de ser o `Term` de verdade.
    old_slug = normalize_slug(source.rotulo)
    if old_slug != normalize_slug(target.rotulo) and source.rotulo not in existing_aliases:
        session.add(TermAlias(term_id=target_id, alias=source.rotulo))

    # Tentativas de Feynman (fase 13) também migram -- a gravação continua
    # valendo como prática do conceito, só passa a apontar pro termo que
    # ficou.
    for attempt in session.scalars(select(FeynmanAttempt).where(FeynmanAttempt.term_id == source_id)):
        attempt.term = target

    for pin in session.scalars(select(TermPin).where(TermPin.term_id == source_id)):
        already_pinned = session.scalar(
            select(TermPin.id).where(TermPin.term_id == target_id, TermPin.subject_id == pin.subject_id)
        )
        if already_pinned:
            session.delete(pin)
        else:
            pin.term_id = target_id

    session.delete(source)
    session.flush()


def separate_definition(session: Session, definition_id: int, novo_termo_titulo: str) -> Term:
    """O oposto de fundir: move só UMA definição pra outro termo
    (existente ou novo, casado por grafia) -- PLANO.md: "quando duas
    coisas viraram um termo só por engano"."""
    definition = session.get(Definition, definition_id)
    novo_termo = find_or_create_term(session, novo_termo_titulo)
    if definition is not None:
        definition.term = novo_termo
        session.flush()
    return novo_termo
