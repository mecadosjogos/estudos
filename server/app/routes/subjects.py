from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..models import Lesson, Subject

router = APIRouter(prefix="/subjects", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("")
def list_subjects(request: Request, session: Session = Depends(get_session)):
    subjects = session.scalars(select(Subject).order_by(Subject.encerrada_em.is_not(None), Subject.nome)).all()
    return templates.TemplateResponse(request, "subjects.html", {"subjects": subjects})


@router.post("")
def create_subject(
    nome: str = Form(...),
    sigla: str = Form(...),
    cor: str = Form(""),
    diploma_padrao: str = Form(""),
    continua_de_id: str = Form(""),
    session: Session = Depends(get_session),
):
    subject = Subject(
        nome=nome.strip(),
        sigla=sigla.strip().upper(),
        cor=cor.strip() or None,
        diploma_padrao=diploma_padrao.strip().upper() or None,
        continua_de_id=int(continua_de_id) if continua_de_id else None,
    )
    session.add(subject)
    session.commit()
    return RedirectResponse(url="/subjects", status_code=303)


@router.post("/{subject_id}/encerrar")
def encerrar_subject(subject_id: int, session: Session = Depends(get_session)):
    subject = session.get(Subject, subject_id)
    if subject is not None:
        subject.encerrada_em = datetime.now(timezone.utc)
        session.commit()
    return RedirectResponse(url="/subjects", status_code=303)


@router.post("/{subject_id}/reabrir")
def reabrir_subject(subject_id: int, session: Session = Depends(get_session)):
    subject = session.get(Subject, subject_id)
    if subject is not None:
        subject.encerrada_em = None
        session.commit()
    return RedirectResponse(url="/subjects", status_code=303)


@router.get("/{subject_id}")
def subject_detail(request: Request, subject_id: int, session: Session = Depends(get_session)):
    subject = session.get(Subject, subject_id)
    lessons = session.scalars(
        select(Lesson).where(Lesson.subject_id == subject_id).order_by(Lesson.data)
    ).all()
    all_subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    return templates.TemplateResponse(
        request,
        "subject_detail.html",
        {"subject": subject, "lessons": lessons, "all_subjects": all_subjects},
    )


@router.post("/{subject_id}/lessons")
def create_lesson(
    subject_id: int,
    titulo: str = Form(...),
    data: str = Form(...),
    google_doc_url: str = Form(""),
    session: Session = Depends(get_session),
):
    lesson = Lesson(
        subject_id=subject_id,
        titulo=titulo.strip(),
        data=datetime.strptime(data, "%Y-%m-%d").date(),
        google_doc_url=google_doc_url.strip() or None,
    )
    session.add(lesson)
    session.commit()
    return RedirectResponse(url=f"/subjects/{subject_id}", status_code=303)
