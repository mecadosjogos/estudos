"""Aula de consolidação (PLANO.md, "Aula de consolidação"): escolher as
aulas-fonte, baixar o pacote e colar o guia consolidado -- ver
ai/consolidacao.py e a skill /consolidar-guia."""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..ai.consolidacao import (
    aulas_consolidaveis,
    build_pacote,
    criar_consolidacao,
    ingest_consolidacao,
    titulo_padrao,
    trocar_fontes,
)
from ..ai.pipeline import ProcessingError
from ..auth import require_admin, require_session
from ..db import get_session
from ..models import Lesson, Subject, User

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/subjects/{subject_id}/consolidar")
def consolidar_form(
    request: Request,
    subject_id: int,
    erro: str | None = None,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="matéria não encontrada")
    aulas = aulas_consolidaveis(session, subject_id)
    return templates.TemplateResponse(
        request,
        "consolidar.html",
        {
            "subject": subject,
            "aulas": aulas,
            "titulo": titulo_padrao(aulas) if aulas else "",
            "erro": erro,
        },
    )


@router.post("/subjects/{subject_id}/consolidar")
def consolidar_submit(
    subject_id: int,
    titulo: str = Form(""),
    aula_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    try:
        lesson = criar_consolidacao(session, subject_id, aula_ids, titulo)
    except ProcessingError as exc:
        return RedirectResponse(url=f"/subjects/{subject_id}/consolidar?erro={quote(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/lessons/{lesson.id}", status_code=303)


def _consolidacao_or_404(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.tipo != "consolidacao":
        raise HTTPException(status_code=404, detail="consolidação não encontrada")
    return lesson


@router.post("/lessons/{lesson_id}/consolidacao/fontes")
def consolidacao_fontes(
    lesson_id: int,
    aula_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    lesson = _consolidacao_or_404(session, lesson_id)
    try:
        trocar_fontes(session, lesson, aula_ids)
    except ProcessingError as exc:
        return RedirectResponse(url=f"/lessons/{lesson_id}?erro_fontes={quote(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.get("/lessons/{lesson_id}/consolidacao/pacote.md")
def consolidacao_pacote(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _consolidacao_or_404(session, lesson_id)
    try:
        content = build_pacote(session, lesson)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="consolidar-guia-{lesson_id}.md"'},
    )


@router.post("/lessons/{lesson_id}/consolidacao/colar-resposta")
def consolidacao_colar(
    lesson_id: int,
    resposta: str = Form(...),
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Responde JSON (não redireciona): quem cola é a skill, que precisa
    ler o relatório de termos pra revisar antes de encerrar."""
    lesson = _consolidacao_or_404(session, lesson_id)
    try:
        return ingest_consolidacao(session, lesson, resposta)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
