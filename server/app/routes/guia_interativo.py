"""Guia interativo (RUNBOOK.md, "Guia interativo"): a página de estudo de
uma consolidação ou guia focado, montada do guia gravado a cada request
(study/guia_interativo.py), e o pacote/colar da skill /guia-interativo
(ai/guia_interativo.py). Só consolidação e guia focado."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.guia_interativo import aplicar, build_pacote, conteudo_atual
from ..ai.pipeline import ProcessingError
from ..auth import require_admin, require_session
from ..db import get_session
from ..models import GuiaSecao, Lesson, User
from ..study.guia_interativo import montar, render_foco

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _consolidacao(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.tipo != "consolidacao":
        raise HTTPException(status_code=404, detail="guia interativo só existe para consolidação e guia focado")
    return lesson


@router.get("/lessons/{lesson_id}/guia/interativo")
def guia_interativo(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _consolidacao(session, lesson_id)
    secoes = session.scalars(
        select(GuiaSecao).where(GuiaSecao.lesson_id == lesson_id).order_by(GuiaSecao.ordem)
    ).all()
    if not secoes:
        raise HTTPException(status_code=404, detail="a consolidação ainda não tem guia")
    ctx = montar([(s.titulo, s.corpo) for s in secoes], lesson.guia_arvore_json, conteudo_atual(session, lesson))
    fontes = json.loads(lesson.consolidacao_fontes_json or "[]")
    datas = sorted(
        l.data for l in (session.get(Lesson, i) for i in fontes) if l is not None
    )
    return templates.TemplateResponse(
        request,
        "guia_interativo.html",
        {
            "lesson": lesson,
            "titulo": lesson.guia_titulo or lesson.titulo,
            "foco_html": render_foco(lesson.foco_md) if lesson.focado and lesson.foco_md else None,
            "periodo": (datas[0], datas[-1]) if datas else None,
            **ctx,
        },
    )


@router.get("/lessons/{lesson_id}/guia/interativo/pacote.md")
def guia_interativo_pacote(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _consolidacao(session, lesson_id)
    try:
        content = build_pacote(session, lesson)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="guia-interativo-{lesson_id}.md"'},
    )


@router.post("/lessons/{lesson_id}/guia/interativo/colar-resposta")
def guia_interativo_colar(
    lesson_id: int,
    resposta: str = Form(...),
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Responde JSON: a skill lê `rejeitados` e `externos` para corrigir
    e reenviar. Cada envio substitui o anterior por inteiro."""
    lesson = _consolidacao(session, lesson_id)
    try:
        return aplicar(session, lesson, resposta)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
