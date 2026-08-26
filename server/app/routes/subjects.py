import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..models import Assunto, AssuntoCobertura, Ementa, Exam, Lesson, Subject
from ..network.graph import build_rede_json

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


@router.post("/{subject_id}/drive")
def update_subject_drive(
    subject_id: int,
    drive_folder_id: str = Form(""),
    doc_modelo_id: str = Form(""),
    session: Session = Depends(get_session),
):
    """Configuração de sync do Drive (fase 9): a pasta é o sinal de maior
    confiança do vinculador automático, o modelo alimenta o botão "Criar
    doc desta aula"."""
    subject = session.get(Subject, subject_id)
    if subject is not None:
        subject.drive_folder_id = drive_folder_id.strip() or None
        subject.doc_modelo_id = doc_modelo_id.strip() or None
        session.commit()
    return RedirectResponse(url=f"/subjects/{subject_id}", status_code=303)


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

    ementa = session.scalar(select(Ementa).where(Ementa.subject_id == subject_id))
    exams = session.scalars(
        select(Exam).where(Exam.subject_id == subject_id).order_by(Exam.data)
    ).all()
    assuntos_da_materia = session.scalars(
        select(Assunto)
        .join(AssuntoCobertura, AssuntoCobertura.assunto_id == Assunto.id)
        .where(AssuntoCobertura.subject_id == subject_id)
        .order_by(Assunto.titulo)
        .distinct()
    ).all()

    lesson_ids = [lesson.id for lesson in lessons]
    # incluir_coocorrencia=True sempre: o filtro por camada agora é 100%
    # client-side (rede.js, via legenda) -- computar tudo de uma vez evita
    # manter dois JSONs embutidos e dois SELECTs quando o toggle virou
    # instantâneo no navegador de qualquer jeito.
    rede_json = build_rede_json(session, lesson_ids, incluir_coocorrencia=True)
    subject_colors_json = json.dumps({s.id: s.cor for s in all_subjects if s.cor})

    return templates.TemplateResponse(
        request,
        "subject_detail.html",
        {
            "subject": subject,
            "lessons": lessons,
            "all_subjects": all_subjects,
            "ementa": ementa,
            "exams": exams,
            "assuntos_da_materia": assuntos_da_materia,
            "rede_json": rede_json,
            "subject_colors_json": subject_colors_json,
        },
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
