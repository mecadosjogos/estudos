from datetime import date

from app.assuntos import ensure_cobertura, find_or_create_assunto, merge_assuntos, normalize_slug, similar_slugs


def test_normalize_slug_strips_accent_and_case():
    assert normalize_slug("Usucapião Extraordinária") == "usucapiao-extraordinaria"


def test_normalize_slug_never_empty():
    assert normalize_slug("!!!") == "assunto"


def test_similar_slugs_catches_extension():
    assert similar_slugs("capacidade", ["capacidade-de-fato"]) == ["capacidade-de-fato"]


def test_similar_slugs_catches_plural_drift():
    assert similar_slugs("negocio-juridico", ["negocios-juridicos"]) == ["negocios-juridicos"]


def test_similar_slugs_ignores_unrelated():
    assert similar_slugs("posse", ["responsabilidade-civil"]) == []


def test_similar_slugs_respects_limit():
    outros = ["capacidade-a", "capacidade-b", "capacidade-c", "capacidade-d"]
    assert len(similar_slugs("capacidade", outros, limit=3)) == 3


def test_find_or_create_assunto_dedupes_by_slug(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        a = find_or_create_assunto(session, "Prescrição")
        session.commit()
        b = find_or_create_assunto(session, "prescricao")
        session.commit()
        assert a.id == b.id


def test_find_or_create_assunto_keeps_first_titulo(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        find_or_create_assunto(session, "Posse")
        session.commit()
        again = find_or_create_assunto(session, "posse")
        session.commit()
        assert again.titulo == "Posse"


def test_ensure_cobertura_is_idempotent(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import AssuntoCobertura, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        assunto = find_or_create_assunto(session, "Posse")
        session.commit()

        ensure_cobertura(session, assunto.id, subject_id)
        ensure_cobertura(session, assunto.id, subject_id)
        session.commit()

        rows = session.scalars(select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == assunto.id)).all()
        assert len(rows) == 1


def test_merge_assuntos_migrates_links_and_coberturas_without_orphans(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import Assunto, AssuntoCobertura, Lesson, LessonAssunto, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Aula fusão", data=date(2026, 3, 1))
        session.add(lesson)
        session.flush()

        capacidade = find_or_create_assunto(session, "Capacidade")
        capacidade_de_fato = find_or_create_assunto(session, "Capacidade de Fato")
        ensure_cobertura(session, capacidade.id, subject_id)
        ensure_cobertura(session, capacidade_de_fato.id, subject_id)
        link = LessonAssunto(
            lesson_id=lesson.id, deriv_key="assunto:capacidade-de-fato",
            texto_proposto="Capacidade de Fato", assunto_id=capacidade_de_fato.id, status="aceito",
        )
        session.add(link)
        session.commit()

        merge_assuntos(session, source_id=capacidade_de_fato.id, target_id=capacidade.id)
        session.commit()

        assert session.get(Assunto, capacidade_de_fato.id) is None
        migrated_link = session.get(LessonAssunto, link.id)
        assert migrated_link.assunto_id == capacidade.id
        coberturas = session.scalars(
            select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == capacidade.id)
        ).all()
        assert len(coberturas) == 1  # a duplicada (mesma matéria) foi descartada, não duplicada
