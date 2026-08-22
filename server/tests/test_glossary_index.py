from app.glossary.index import load_active_variants
from app.glossary.normalize import normalize_char_preserving
from app.models import Term, TermAlias


def test_includes_own_rotulo_as_implicit_variant(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        term = Term(slug="usucapiao", rotulo="Usucapião")
        session.add(term)
        session.commit()
        term_id = term.id

        variants = load_active_variants(session)
        assert any(v.term_id == term_id and v.normalized == normalize_char_preserving("Usucapião") for v in variants)


def test_includes_all_aliases(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        term = Term(slug="negocio-juridico", rotulo="Negócio jurídico")
        session.add(term)
        session.flush()
        session.add(TermAlias(term_id=term.id, alias="negocios juridicos"))
        session.commit()
        term_id = term.id

        variants = load_active_variants(session)
        normalized_forms = {v.normalized for v in variants if v.term_id == term_id}
        assert normalize_char_preserving("Negócio jurídico") in normalized_forms
        assert "negocios juridicos" in normalized_forms


def test_excludes_terms_with_destacar_false(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        session.add(Term(slug="oculto", rotulo="Termo oculto", destacar=False))
        session.commit()

        variants = load_active_variants(session)
        assert not any(v.display == "Termo oculto" for v in variants)


def test_deduplicates_identical_normalized_forms(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        term = Term(slug="boa-fe", rotulo="Boa-fé")
        session.add(term)
        session.flush()
        # alias que normaliza pro mesmo valor do rótulo (só maiúscula muda)
        session.add(TermAlias(term_id=term.id, alias="BOA-FÉ"))
        session.commit()

        variants = load_active_variants(session)
        normalized_forms = [v.normalized for v in variants]
        assert normalized_forms.count(normalize_char_preserving("Boa-fé")) == 1


def test_no_active_terms_returns_empty_list(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        assert load_active_variants(session) == []
