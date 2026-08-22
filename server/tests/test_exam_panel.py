from datetime import date, timedelta

from sqlalchemy import select

from app.assuntos import ensure_cobertura, find_or_create_assunto
from app.study.exam_panel import compute_exam_panel


def _subject_id(session, sigla="TGDC"):
    from app.models import Subject

    return session.scalar(select(Subject.id).where(Subject.sigla == sigla))


def _make_lesson(session, subject_id, titulo="Aula exam panel"):
    from app.models import Lesson

    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()
    return lesson


def _link_lesson_to_assunto(session, lesson_id, assunto_id):
    from app.models import LessonAssunto

    session.add(LessonAssunto(
        lesson_id=lesson_id, deriv_key=f"assunto:test:{lesson_id}:{assunto_id}",
        texto_proposto="x", assunto_id=assunto_id, status="aceito",
    ))


def _make_card(session, lesson_id, due_date=None, deriv_key_suffix="1"):
    from app.models import CardProposal

    card = CardProposal(
        lesson_id=lesson_id, deriv_key=f"card:{lesson_id}:{deriv_key_suffix}",
        frente="F", verso="V", start_s=0.0, end_s=1.0, status="aceito", due_date=due_date,
    )
    session.add(card)
    session.flush()
    return card


def _make_exam(session, subject_id, assunto_ids, dias=9):
    from app.models import Exam, ExamScope

    exam = Exam(subject_id=subject_id, titulo="Prova teste", data=date.today() + timedelta(days=dias))
    session.add(exam)
    session.flush()
    for aid in assunto_ids:
        session.add(ExamScope(exam_id=exam.id, assunto_id=aid))
    session.commit()
    return exam


def test_panel_counts_topicos_and_dados(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        a1 = find_or_create_assunto(session, "Posse")
        a2 = find_or_create_assunto(session, "Propriedade")
        ensure_cobertura(session, a1.id, subject_id)  # status="dado"
        # a2 fica sem cobertura nenhuma -- nem "dado" nem "pendente"
        session.commit()

        exam = _make_exam(session, subject_id, [a1.id, a2.id])
        panel = compute_exam_panel(session, exam)

        assert panel.total_topicos == 2
        assert panel.dados == 1


def test_panel_marks_pending_topics_as_not_dado(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        a1 = find_or_create_assunto(session, "Usucapião")
        ensure_cobertura(session, a1.id, subject_id, origem="ementa", status="pendente")
        session.commit()

        exam = _make_exam(session, subject_id, [a1.id])
        panel = compute_exam_panel(session, exam)

        assert panel.total_topicos == 1
        assert panel.dados == 0


def test_panel_counts_overdue_cards_and_computes_ritmo(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Posse")
        lesson = _make_lesson(session, subject_id)
        _link_lesson_to_assunto(session, lesson.id, assunto.id)
        ensure_cobertura(session, assunto.id, subject_id)
        ontem = date.today() - timedelta(days=1)
        amanha = date.today() + timedelta(days=1)
        _make_card(session, lesson.id, due_date=ontem, deriv_key_suffix="vencido")
        _make_card(session, lesson.id, due_date=amanha, deriv_key_suffix="futuro")
        session.commit()

        exam = _make_exam(session, subject_id, [assunto.id], dias=2)
        panel = compute_exam_panel(session, exam)

        assert panel.cards_vencidos == 1
        assert panel.ritmo_por_dia == 1  # 1 vencido / 2 dias, arredondado pra cima


def test_panel_computes_estudados_and_taxa_de_acerto(app_env):
    from app.db import holder
    from app.models import ReviewLog

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Posse")
        lesson = _make_lesson(session, subject_id)
        _link_lesson_to_assunto(session, lesson.id, assunto.id)
        ensure_cobertura(session, assunto.id, subject_id)
        card = _make_card(session, lesson.id)
        session.add(ReviewLog(card_id=card.id, confianca="acho_que_sei", qualidade=4, acertou=True))
        session.add(ReviewLog(card_id=card.id, confianca="chutei", qualidade=1, acertou=False))
        session.commit()

        exam = _make_exam(session, subject_id, [assunto.id])
        panel = compute_exam_panel(session, exam)

        assert panel.estudados == 1
        assert len(panel.mais_fracos) == 1
        assert panel.mais_fracos[0].taxa_acerto == 0.5


def test_panel_counts_sem_material(app_env):
    from app.db import holder
    from app.models import Material, MaterialUse

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        com_material = find_or_create_assunto(session, "Posse")
        sem_material = find_or_create_assunto(session, "Propriedade")
        lesson1 = _make_lesson(session, subject_id, titulo="Aula 1")
        lesson2 = _make_lesson(session, subject_id, titulo="Aula 2")
        _link_lesson_to_assunto(session, lesson1.id, com_material.id)
        _link_lesson_to_assunto(session, lesson2.id, sem_material.id)
        ensure_cobertura(session, com_material.id, subject_id)
        ensure_cobertura(session, sem_material.id, subject_id)

        material = Material(titulo="Slide", origem="texto", conteudo_md="x", status="ok")
        session.add(material)
        session.flush()
        session.add(MaterialUse(material_id=material.id, subject_id=subject_id, lesson_id=lesson1.id))
        session.commit()

        exam = _make_exam(session, subject_id, [com_material.id, sem_material.id])
        panel = compute_exam_panel(session, exam)

        assert panel.sem_material == 1


def test_panel_empty_scope(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        exam = _make_exam(session, subject_id, [])
        panel = compute_exam_panel(session, exam)
        assert panel.total_topicos == 0
        assert panel.cards_vencidos == 0
