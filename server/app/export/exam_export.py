"""Apanhado do escopo da prova (PLANO.md, fase 14): um documento só,
"pra estudar no papel na véspera", montado a partir do guia de aula de
cada aula que cobre um assunto do escopo -- o guia já É a versão
condensada e legível da aula, reaproveitar em vez de reconstruir algo
novo a partir dos blocos crus da aula editada."""

import html

import markdown as markdown_lib
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Exam, Lesson, LessonAssunto


def build_exam_scope_html(session: Session, exam: Exam) -> str:
    parts = [f"<h1>{html.escape(exam.titulo)} — {exam.subject.sigla}</h1>", f"<p class='muted'>{exam.data.isoformat()}</p>"]

    for scope in exam.escopo:
        assunto = scope.assunto
        parts.append(f"<h2>{html.escape(assunto.titulo)}</h2>")

        lesson_ids = session.scalars(
            select(LessonAssunto.lesson_id).where(
                LessonAssunto.assunto_id == assunto.id, LessonAssunto.status == "aceito"
            )
        ).all()
        lessons = session.scalars(
            select(Lesson).where(Lesson.id.in_(lesson_ids)).order_by(Lesson.data)
        ).all() if lesson_ids else []

        if not lessons:
            parts.append("<p class='muted'>Nenhuma aula vinculada ainda.</p>")
            continue

        for lesson in lessons:
            parts.append(f"<p class='muted'>{lesson.titulo} — {lesson.data.isoformat()}</p>")
            if lesson.guia_md:
                parts.append(markdown_lib.markdown(lesson.guia_md, extensions=["extra"]))
            elif lesson.resumo:
                parts.append(f"<p>{html.escape(lesson.resumo)}</p>")
            else:
                parts.append("<p class='muted'>Aula ainda não processada.</p>")

    return "".join(parts)
