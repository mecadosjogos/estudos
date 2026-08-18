from datetime import date

from app.context.window import build_context_for_assunto


def _lesson_with_transcript(session, subject_sigla, titulo, texto, dia):
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == subject_sigla))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, dia))
    session.add(lesson)
    session.flush()
    session.add(Transcript(lesson_id=lesson.id, engine="e", worker_name="w", full_text=texto, duration_s=5.0))
    session.commit()
    return lesson.id


def test_build_context_concatenates_literal_transcript_of_linked_lessons(app_env):
    from app.assuntos import ensure_cobertura, find_or_create_assunto
    from app.db import holder
    from app.models import LessonAssunto

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Subject

        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson1 = _lesson_with_transcript(session, "TGDC", "Aula 1", "posse mansa e pacifica", 1)
        lesson2 = _lesson_with_transcript(session, "TGDC", "Aula 2", "usucapiao extraordinaria quinze anos", 8)

        assunto = find_or_create_assunto(session, "Usucapião")
        ensure_cobertura(session, assunto.id, subject_id)
        session.add(LessonAssunto(
            lesson_id=lesson1, deriv_key="assunto:usucapiao", texto_proposto="Usucapião",
            assunto_id=assunto.id, status="aceito",
        ))
        session.add(LessonAssunto(
            lesson_id=lesson2, deriv_key="assunto:usucapiao", texto_proposto="Usucapião",
            assunto_id=assunto.id, status="aceito",
        ))
        session.commit()

        context = build_context_for_assunto(session, assunto.id)

        assert "posse mansa e pacifica" in context
        assert "usucapiao extraordinaria quinze anos" in context
        assert context.index("Aula 1") < context.index("Aula 2")  # ordem cronológica


def test_build_context_ignores_pending_and_discarded_links(app_env):
    from app.assuntos import ensure_cobertura, find_or_create_assunto
    from app.db import holder
    from app.models import LessonAssunto

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Subject

        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson1 = _lesson_with_transcript(session, "TGDC", "Aula pendente", "nao deve aparecer", 1)

        assunto = find_or_create_assunto(session, "Posse")
        ensure_cobertura(session, assunto.id, subject_id)
        session.add(LessonAssunto(
            lesson_id=lesson1, deriv_key="assunto:posse", texto_proposto="Posse",
            assunto_id=assunto.id, status="pendente",
        ))
        session.commit()

        context = build_context_for_assunto(session, assunto.id)
        assert context == ""


def test_build_context_never_uses_edited_lesson_text(app_env):
    """PLANO.md: o recorte de contexto é sempre a transcrição literal,
    nunca a aula editada -- mesmo que o resumo exista, não deve aparecer."""
    from app.assuntos import ensure_cobertura, find_or_create_assunto
    from app.db import holder
    from app.models import Lesson, LessonAssunto

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Subject

        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson_id = _lesson_with_transcript(session, "TGDC", "Aula", "texto literal do whisper", 1)
        lesson = session.get(Lesson, lesson_id)
        lesson.resumo = "um resumo que nunca deveria entrar no contexto"

        assunto = find_or_create_assunto(session, "Posse")
        ensure_cobertura(session, assunto.id, subject_id)
        session.add(LessonAssunto(
            lesson_id=lesson_id, deriv_key="assunto:posse", texto_proposto="Posse",
            assunto_id=assunto.id, status="aceito",
        ))
        session.commit()

        context = build_context_for_assunto(session, assunto.id)
        assert "texto literal do whisper" in context
        assert "resumo que nunca deveria" not in context
