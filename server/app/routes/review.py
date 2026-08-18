"""Fila de revisão espaçada (PLANO.md, fase 7)."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session
from ..db import get_session
from ..models import CardProposal, Subject
from ..study.scheduler import CONFIDENCE_LEVELS, build_daily_queue, calibration_report, exam_mode_queue, submit_review

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/revisao")
def daily_queue(request: Request):
    """A fila do dia é montada no cliente a partir de /revisao/fila.json —
    isso é o que permite continuar revisando sem rede (PLANO.md, fase 7)."""
    return templates.TemplateResponse(
        request,
        "review.html",
        {"daily_cap": config.REVIEW_DAILY_CAP, "confidence_levels": CONFIDENCE_LEVELS},
    )


@router.get("/revisao/fila.json")
def daily_queue_json(session: Session = Depends(get_session)):
    """Fila do dia em JSON — o cliente guarda isto em localStorage pra
    revisar sem rede no meio do trajeto (PLANO.md, fase 7)."""
    today = datetime.now(timezone.utc).date()
    queue, in_recovery = build_daily_queue(session, daily_cap=config.REVIEW_DAILY_CAP, today=today)
    return JSONResponse(
        {
            "in_recovery": in_recovery,
            "cards": [
                {
                    "id": card.id,
                    "lesson_id": card.lesson_id,
                    "frente": card.frente,
                    "verso": card.verso,
                    "start_s": card.start_s,
                    "subject_sigla": card.lesson.subject.sigla,
                }
                for card in queue
            ],
        }
    )


@router.post("/revisao/{card_id}/responder")
def answer_card(
    request: Request,
    card_id: int,
    confianca: str = Form(...),
    shortcut: int = Form(...),
    queue_url: str = Form("/revisao"),
    session: Session = Depends(get_session),
):
    card = session.get(CardProposal, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card não encontrado")
    if confianca not in CONFIDENCE_LEVELS:
        raise HTTPException(status_code=400, detail="confiança inválida")
    if shortcut not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="atalho inválido — use 1 a 4")

    log = submit_review(session, card, confianca=confianca, shortcut=shortcut)
    # PLANO.md: errou o card -> botão que toca os 30s de origem, antes de
    # seguir pro próximo. Por isso o POST não redireciona direto.
    return templates.TemplateResponse(
        request,
        "review_feedback.html",
        {"card": card, "log": log, "queue_url": queue_url},
    )


@router.post("/revisao/{card_id}/responder.json")
def answer_card_json(
    card_id: int,
    confianca: str = Form(...),
    shortcut: int = Form(...),
    session: Session = Depends(get_session),
):
    """Mesma coisa que /responder, mas devolve JSON — usada pela fila
    client-side (localStorage) pra sincronizar sem recarregar a página."""
    card = session.get(CardProposal, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card não encontrado")
    if confianca not in CONFIDENCE_LEVELS:
        raise HTTPException(status_code=400, detail="confiança inválida")
    if shortcut not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="atalho inválido — use 1 a 4")

    log = submit_review(session, card, confianca=confianca, shortcut=shortcut)
    return JSONResponse({"acertou": log.acertou, "due_date": str(card.due_date)})


@router.get("/revisao/calibracao")
def calibration(request: Request, session: Session = Depends(get_session)):
    report = calibration_report(session)
    return templates.TemplateResponse(request, "calibration.html", {"report": report})


@router.get("/revisao/prova/{subject_id}")
def exam_mode(request: Request, subject_id: int, session: Session = Depends(get_session)):
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="matéria não encontrada")

    queue = exam_mode_queue(session, subject_id)
    current = queue[0] if queue else None
    return templates.TemplateResponse(
        request,
        "exam_review.html",
        {
            "current": current,
            "remaining": len(queue),
            "in_recovery": False,
            "daily_cap": None,
            "confidence_levels": CONFIDENCE_LEVELS,
            "queue_url": f"/revisao/prova/{subject_id}",
            "subject": subject,
        },
    )
