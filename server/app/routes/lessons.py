from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..models import Lesson, Subject

router = APIRouter(prefix="/lessons", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/{lesson_id}")
def lesson_detail(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    all_subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    return templates.TemplateResponse(
        request, "lesson_detail.html", {"lesson": lesson, "all_subjects": all_subjects}
    )


@router.post("/{lesson_id}")
def update_lesson(
    lesson_id: int,
    titulo: str = Form(...),
    data: str = Form(...),
    google_doc_url: str = Form(""),
    session: Session = Depends(get_session),
):
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        lesson.titulo = titulo.strip()
        lesson.data = datetime.strptime(data, "%Y-%m-%d").date()
        lesson.google_doc_url = google_doc_url.strip() or None
        session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/move")
def move_lesson(lesson_id: int, subject_id: int = Form(...), session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        # Cards e definições ligados à aula seguem por FK — não há nada para migrar
        # à parte, já que nenhum dos dois carrega subject_id próprio (ver PLANO.md,
        # Integridade #3: matéria não é atributo do trecho).
        lesson.subject_id = subject_id
        session.commit()
    return RedirectResponse(url=f"/subjects/{subject_id}", status_code=303)
