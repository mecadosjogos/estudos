"""Ementa (opcional), provas e o painel do plano regressivo (PLANO.md,
fase 14)."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..ementa import import_ementa
from ..export.exam_export import build_exam_scope_html
from ..export.pdf import render_html_to_pdf
from ..models import Assunto, Exam, ExamScope, Subject
from ..study.exam_panel import compute_exam_panel

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _get_subject_or_404(session: Session, subject_id: int) -> Subject:
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="matéria não encontrada")
    return subject


def _get_exam_or_404(session: Session, exam_id: int) -> Exam:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="prova não encontrada")
    return exam


@router.post("/subjects/{subject_id}/ementa")
def post_ementa(subject_id: int, topicos: str = Form(...), session: Session = Depends(get_session)):
    _get_subject_or_404(session, subject_id)
    titulos = topicos.splitlines()
    import_ementa(session, subject_id, titulos)
    return RedirectResponse(url=f"/subjects/{subject_id}", status_code=303)


@router.post("/subjects/{subject_id}/exams")
def create_exam(
    subject_id: int,
    titulo: str = Form(...),
    data: str = Form(...),
    assunto_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
):
    _get_subject_or_404(session, subject_id)
    exam = Exam(subject_id=subject_id, titulo=titulo.strip(), data=datetime.strptime(data, "%Y-%m-%d").date())
    session.add(exam)
    session.flush()
    for assunto_id in set(assunto_ids):
        session.add(ExamScope(exam_id=exam.id, assunto_id=assunto_id))
    session.commit()
    return RedirectResponse(url=f"/exams/{exam.id}", status_code=303)


@router.get("/exams/{exam_id}")
def exam_detail(request: Request, exam_id: int, session: Session = Depends(get_session)):
    exam = _get_exam_or_404(session, exam_id)
    panel = compute_exam_panel(session, exam)
    escopo_ids = [s.assunto_id for s in exam.escopo]
    outros_stmt = select(Assunto).order_by(Assunto.titulo)
    if escopo_ids:
        outros_stmt = outros_stmt.where(Assunto.id.not_in(escopo_ids))
    outros_assuntos = session.scalars(outros_stmt).all()
    return templates.TemplateResponse(
        request, "exam_detail.html", {"exam": exam, "panel": panel, "outros_assuntos": outros_assuntos}
    )


@router.post("/exams/{exam_id}/escopo")
def add_to_scope(exam_id: int, assunto_id: int = Form(...), session: Session = Depends(get_session)):
    exam = _get_exam_or_404(session, exam_id)
    already = session.scalar(
        select(ExamScope.id).where(ExamScope.exam_id == exam_id, ExamScope.assunto_id == assunto_id)
    )
    if not already:
        session.add(ExamScope(exam_id=exam_id, assunto_id=assunto_id))
        session.commit()
    return RedirectResponse(url=f"/exams/{exam_id}", status_code=303)


@router.post("/exams/{exam_id}/escopo/{assunto_id}/remover")
def remove_from_scope(exam_id: int, assunto_id: int, session: Session = Depends(get_session)):
    scope = session.scalar(
        select(ExamScope).where(ExamScope.exam_id == exam_id, ExamScope.assunto_id == assunto_id)
    )
    if scope is not None:
        session.delete(scope)
        session.commit()
    return RedirectResponse(url=f"/exams/{exam_id}", status_code=303)


@router.get("/exams/{exam_id}/apanhado.pdf")
def download_apanhado_pdf(exam_id: int, session: Session = Depends(get_session)):
    exam = _get_exam_or_404(session, exam_id)
    html = build_exam_scope_html(session, exam)
    pdf_bytes = render_html_to_pdf(html)
    filename = f"apanhado-prova-{exam_id}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
