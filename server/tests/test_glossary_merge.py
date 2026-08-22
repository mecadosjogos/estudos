from sqlalchemy import select

from app.glossary.merge import find_or_create_term, merge_terms, separate_definition
from app.models import Definition, FeynmanAttempt, Term, TermAlias, TermPin


def test_find_or_create_term_dedupes_by_slug(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        a = find_or_create_term(session, "Boa-fé")
        session.commit()
        b = find_or_create_term(session, "boa fe")
        session.commit()
        assert a.id == b.id


def test_find_or_create_term_keeps_first_rotulo(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        find_or_create_term(session, "Posse")
        session.commit()
        again = find_or_create_term(session, "posse")
        session.commit()
        assert again.rotulo == "Posse"


def test_merge_terms_migrates_definitions_aliases_and_pins_without_orphans(app_env):
    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

        culpa = find_or_create_term(session, "Culpa")
        culpa_lato = find_or_create_term(session, "Culpa em sentido lato")
        session.add(TermAlias(term_id=culpa_lato.id, alias="culpa lato sensu"))
        session.flush()

        definition = Definition(term_id=culpa_lato.id, subject_id=subject_id, definicao_md="Definição de teste")
        session.add(definition)
        session.flush()

        pin = TermPin(term_id=culpa_lato.id, subject_id=subject_id, definition_id=definition.id)
        session.add(pin)
        session.commit()

        merge_terms(session, source_id=culpa_lato.id, target_id=culpa.id)
        session.commit()

        assert session.get(Term, culpa_lato.id) is None

        migrated_definition = session.get(Definition, definition.id)
        assert migrated_definition.term_id == culpa.id

        migrated_pin = session.get(TermPin, pin.id)
        assert migrated_pin.term_id == culpa.id

        aliases = {a.alias for a in session.scalars(select(TermAlias).where(TermAlias.term_id == culpa.id))}
        assert "culpa lato sensu" in aliases
        # a grafia antiga do termo fundido também vira alias, senão some do texto
        assert "Culpa em sentido lato" in aliases


def test_merge_terms_drops_duplicate_pin_instead_of_erroring(app_env):
    """Alvo e origem podem, cada um, já ter uma preferência fixada pra
    mesma matéria antes da fusão -- só uma pode sobreviver (a do alvo, já
    que é ele quem fica)."""
    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

        alvo = find_or_create_term(session, "Dolo")
        origem = find_or_create_term(session, "Dolo Eventual")

        definition_alvo = Definition(term_id=alvo.id, subject_id=subject_id, definicao_md="Def alvo")
        session.add(definition_alvo)
        session.flush()
        pin_alvo = TermPin(term_id=alvo.id, subject_id=subject_id, definition_id=definition_alvo.id)
        session.add(pin_alvo)
        session.flush()

        definition_origem = Definition(term_id=origem.id, subject_id=subject_id, definicao_md="Def origem")
        session.add(definition_origem)
        session.flush()
        pin_origem = TermPin(term_id=origem.id, subject_id=subject_id, definition_id=definition_origem.id)
        session.add(pin_origem)
        session.commit()

        merge_terms(session, source_id=origem.id, target_id=alvo.id)
        session.commit()

        remaining_pins = session.scalars(
            select(TermPin).where(TermPin.term_id == alvo.id, TermPin.subject_id == subject_id)
        ).all()
        assert len(remaining_pins) == 1


def test_merge_terms_skips_old_rotulo_alias_when_already_present_on_target(app_env):
    """Se o alvo já tinha, por algum motivo, um alias igual à grafia
    antiga do termo fundido, não pode tentar inserir de novo (violaria a
    unicidade global de `term_alias.alias`)."""
    from app.db import holder

    with holder.SessionLocal() as session:
        alvo = find_or_create_term(session, "Culpa")
        session.add(TermAlias(term_id=alvo.id, alias="Culpa em sentido lato"))
        session.flush()

        origem = find_or_create_term(session, "Culpa em sentido lato")
        session.commit()

        merge_terms(session, source_id=origem.id, target_id=alvo.id)
        session.commit()

        aliases = session.scalars(select(TermAlias).where(TermAlias.term_id == alvo.id)).all()
        assert sum(1 for a in aliases if a.alias == "Culpa em sentido lato") == 1


def test_merge_terms_migrates_feynman_attempts(app_env):
    """Fase 13: uma gravação de prática continua valendo depois da fusão,
    só passa a apontar pro termo que ficou."""
    from app.db import holder

    with holder.SessionLocal() as session:
        alvo = find_or_create_term(session, "Dolo")
        origem = find_or_create_term(session, "Dolo Eventual")
        attempt = FeynmanAttempt(term_id=origem.id, audio_path="/tmp/x.webm", status="transcrito")
        session.add(attempt)
        session.commit()
        attempt_id = attempt.id

        merge_terms(session, source_id=origem.id, target_id=alvo.id)
        session.commit()

        assert session.get(FeynmanAttempt, attempt_id).term_id == alvo.id


def test_separate_definition_moves_only_that_definition(app_env):
    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

        termo = find_or_create_term(session, "Ato jurídico")
        ficou = Definition(term_id=termo.id, subject_id=subject_id, definicao_md="Fica aqui")
        vai = Definition(term_id=termo.id, subject_id=subject_id, definicao_md="Vai pra outro termo")
        session.add_all([ficou, vai])
        session.commit()

        novo_termo = separate_definition(session, vai.id, "Negócio jurídico")
        session.commit()

        assert session.get(Definition, ficou.id).term_id == termo.id
        assert session.get(Definition, vai.id).term_id == novo_termo.id
        assert novo_termo.id != termo.id
