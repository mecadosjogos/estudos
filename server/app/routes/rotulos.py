"""Passada de rótulos no guia (RUNBOOK.md, "Rótulos do guia"): baixar o
pacote e colar as seções rotuladas -- ver ai/rotulos.py e a skill
/rotular-guia. Vale para aula normal e consolidação; guia focado fica de
fora por enquanto."""

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..ai.pipeline import ProcessingError
from ..ai.rotulos import aplicar, build_pacote
from ..auth import require_admin, require_session
from ..db import get_session
from ..models import Lesson, User
from .lessons import _rebuild_guia_md

router = APIRouter(dependencies=[Depends(require_session)])


def _lesson_com_guia(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")
    return lesson


@router.get("/lessons/{lesson_id}/guia/rotulos/pacote.md")
def rotulos_pacote(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _lesson_com_guia(session, lesson_id)
    try:
        content = build_pacote(session, lesson)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="rotulos-guia-{lesson_id}.md"'},
    )


@router.post("/lessons/{lesson_id}/guia/rotulos/colar-resposta")
def rotulos_colar(
    lesson_id: int,
    resposta: str = Form(...),
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Responde JSON: a skill lê `rejeitadas` para corrigir e reenviar só
    aquelas seções. Reenviar é seguro -- seção que já está igual conta em
    `sem_mudanca`."""
    lesson = _lesson_com_guia(session, lesson_id)
    try:
        relatorio = aplicar(session, lesson, resposta)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if relatorio["alteradas"]:
        _rebuild_guia_md(session, lesson)
        session.commit()
    return relatorio
