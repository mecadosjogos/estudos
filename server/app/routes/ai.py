"""Rotas de IA e aprovação (PLANO.md, fase 6): processar (automático ou
manual), aula editada, e a tela de aprovação de cards/datas."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.bridge import build_prompt, package_as_markdown
from ..ai.budget import BudgetExceededError
from ..ai.client import get_ai_client
from ..ai.pipeline import ProcessingError, build_prompt_for_lesson, ingest_manual_response, process_lesson_automatically
from ..auth import require_session
from ..db import get_session
from ..models import AnnouncementProposal, CardProposal, EditedBlock, Lesson

router = APIRouter(prefix="/lessons", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _get_lesson_or_404(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    return lesson


@router.post("/{lesson_id}/processar")
def process_automatically(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        client = get_ai_client()
        process_lesson_automatically(session, lesson, client)
    except (ProcessingError, BudgetExceededError, RuntimeError) as exc:
        return RedirectResponse(
            url=f"/lessons/{lesson_id}?erro_ia={_url_escape(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/lessons/{lesson_id}/aula-editada", status_code=303)


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


@router.get("/{lesson_id}/pacote.md")
def download_package(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        prompt, _signals = build_prompt_for_lesson(lesson)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = package_as_markdown(lesson, prompt)
    filename = f"processar-aula-{lesson_id}.md"
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lesson_id}/colar-resposta")
def paste_response_form(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    return templates.TemplateResponse(request, "paste_response.html", {"lesson": lesson})


@router.post("/{lesson_id}/colar-resposta")
def paste_response_submit(
    lesson_id: int, resposta: str = Form(...), session: Session = Depends(get_session)
):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        ingest_manual_response(session, lesson, resposta)
    except (ProcessingError, ValueError) as exc:
        return RedirectResponse(
            url=f"/lessons/{lesson_id}/colar-resposta?erro={_url_escape(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/lessons/{lesson_id}/aula-editada", status_code=303)


@router.get("/{lesson_id}/aula-editada")
def edited_lesson(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    blocks = session.scalars(
        select(EditedBlock)
        .where(EditedBlock.lesson_id == lesson_id, EditedBlock.orfao_em.is_(None))
        .order_by(EditedBlock.ordem)
    ).all()
    return templates.TemplateResponse(request, "edited_lesson.html", {"lesson": lesson, "blocks": blocks})


@router.post("/{lesson_id}/blocks/{block_id}/observacao")
def save_block_observation(
    lesson_id: int, block_id: int, observacao: str = Form(""), session: Session = Depends(get_session)
):
    block = session.get(EditedBlock, block_id)
    if block is None or block.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="bloco não encontrado")
    block.observacao = observacao.strip() or None
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aula-editada", status_code=303)


@router.post("/{lesson_id}/blocks/{block_id}/confirmar")
def confirm_block(lesson_id: int, block_id: int, session: Session = Depends(get_session)):
    """Confirma uma citação de baixa confiança (PLANO.md) — um toque, não
    pergunta de novo depois."""
    block = session.get(EditedBlock, block_id)
    if block is None or block.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="bloco não encontrado")
    block.confirmado_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aula-editada", status_code=303)


@router.get("/{lesson_id}/aprovacao")
def approval_screen(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    cards = session.scalars(
        select(CardProposal).where(CardProposal.lesson_id == lesson_id, CardProposal.status == "pendente")
    ).all()
    announcements = session.scalars(
        select(AnnouncementProposal).where(
            AnnouncementProposal.lesson_id == lesson_id, AnnouncementProposal.status == "pendente"
        )
    ).all()
    return templates.TemplateResponse(
        request, "approval.html", {"lesson": lesson, "cards": cards, "announcements": announcements}
    )


class CardEditBody(BaseModel):
    frente: str
    verso: str


@router.post("/{lesson_id}/cards/{card_id}/aceitar")
def accept_card(lesson_id: int, card_id: int, session: Session = Depends(get_session)):
    card = session.get(CardProposal, card_id)
    if card is None or card.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="card não encontrado")
    card.status = "aceito"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)


@router.post("/{lesson_id}/cards/{card_id}/descartar")
def discard_card(lesson_id: int, card_id: int, session: Session = Depends(get_session)):
    card = session.get(CardProposal, card_id)
    if card is None or card.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="card não encontrado")
    card.status = "descartado"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)


@router.post("/{lesson_id}/cards/{card_id}/editar")
def edit_card(
    lesson_id: int,
    card_id: int,
    frente: str = Form(...),
    verso: str = Form(...),
    session: Session = Depends(get_session),
):
    card = session.get(CardProposal, card_id)
    if card is None or card.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="card não encontrado")
    card.frente = frente
    card.verso = verso
    card.status = "aceito"
    card.editado_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)


@router.post("/{lesson_id}/announcements/{announcement_id}/aceitar")
def accept_announcement(lesson_id: int, announcement_id: int, session: Session = Depends(get_session)):
    ann = session.get(AnnouncementProposal, announcement_id)
    if ann is None or ann.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="data não encontrada")
    ann.status = "aceito"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)


@router.post("/{lesson_id}/announcements/{announcement_id}/descartar")
def discard_announcement(lesson_id: int, announcement_id: int, session: Session = Depends(get_session)):
    ann = session.get(AnnouncementProposal, announcement_id)
    if ann is None or ann.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="data não encontrada")
    ann.status = "descartado"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)
