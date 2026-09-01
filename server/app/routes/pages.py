from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session
from ..db import get_session
from ..models import Subject
from ..study.scheduler import build_daily_queue

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    queue, in_recovery = build_daily_queue(session, daily_cap=config.REVIEW_DAILY_CAP)
    return templates.TemplateResponse(
        request,
        "home.html",
        {"subjects": subjects, "review_count": len(queue), "review_recovery": in_recovery},
    )


@router.get("/estudar")
def estudar(request: Request, session: Session = Depends(get_session)):
    subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    queue, in_recovery = build_daily_queue(session, daily_cap=config.REVIEW_DAILY_CAP)
    return templates.TemplateResponse(
        request,
        "estudar.html",
        {"subjects": subjects, "review_count": len(queue), "review_recovery": in_recovery},
    )
