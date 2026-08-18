"""Assunto -- global, atravessa matérias e semestres (PLANO.md, fase 8):
listagem, página do assunto, e as ferramentas de correção (fundir,
renomear, separar um vínculo)."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assuntos import ensure_cobertura, find_or_create_assunto, merge_assuntos
from ..auth import require_session
from ..db import get_session
from ..models import (
    AssuntoCobertura,
    CardProposal,
    Lesson,
    LessonAssunto,
    ReviewLog,
)
from ..models import Assunto

router = APIRouter(prefix="/assuntos", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _get_assunto_or_404(session: Session, assunto_id: int) -> Assunto:
    assunto = session.get(Assunto, assunto_id)
    if assunto is None:
        raise HTTPException(status_code=404, detail="assunto não encontrado")
    return assunto


@router.get("")
def list_assuntos(request: Request, q: str = "", session: Session = Depends(get_session)):
    stmt = select(Assunto).order_by(Assunto.titulo)
    if q.strip():
        stmt = stmt.where(Assunto.titulo.ilike(f"%{q.strip()}%"))
    assuntos = session.scalars(stmt).all()

    aula_counts = {
        assunto.id: len(
            session.scalars(
                select(LessonAssunto.id).where(
                    LessonAssunto.assunto_id == assunto.id, LessonAssunto.status == "aceito"
                )
            ).all()
        )
        for assunto in assuntos
    }
    return templates.TemplateResponse(
        request, "assuntos.html", {"assuntos": assuntos, "q": q, "aula_counts": aula_counts}
    )


@router.get("/{assunto_id}")
def assunto_detail(request: Request, assunto_id: int, session: Session = Depends(get_session)):
    assunto = _get_assunto_or_404(session, assunto_id)

    coberturas = session.scalars(
        select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == assunto_id)
    ).all()

    links = session.scalars(
        select(LessonAssunto).where(LessonAssunto.assunto_id == assunto_id, LessonAssunto.status == "aceito")
    ).all()
    lesson_ids = [link.lesson_id for link in links]
    lessons_by_id = {lesson.id: lesson for lesson in session.scalars(
        select(Lesson).where(Lesson.id.in_(lesson_ids))
    ).all()} if lesson_ids else {}

    cards = session.scalars(
        select(CardProposal).where(CardProposal.lesson_id.in_(lesson_ids), CardProposal.status == "aceito")
    ).all() if lesson_ids else []

    card_ids = [c.id for c in cards]
    logs = session.scalars(select(ReviewLog).where(ReviewLog.card_id.in_(card_ids))).all() if card_ids else []
    total_revisoes = len(logs)
    acertos = sum(1 for log in logs if log.acertou)
    taxa_acerto = (acertos / total_revisoes) if total_revisoes else None
    ultima_revisao = max((log.revisado_em for log in logs), default=None)
    vencidos = sum(1 for c in cards if c.due_date is not None)

    outras = session.scalars(select(Assunto).where(Assunto.id != assunto_id).order_by(Assunto.titulo)).all()

    return templates.TemplateResponse(
        request,
        "assunto_detail.html",
        {
            "assunto": assunto,
            "coberturas": coberturas,
            "links": links,
            "lessons_by_id": lessons_by_id,
            "cards_count": len(cards),
            "taxa_acerto": taxa_acerto,
            "ultima_revisao": ultima_revisao,
            "vencidos": vencidos,
            "outras": outras,
        },
    )


@router.post("/{assunto_id}/renomear")
def renomear_assunto(
    assunto_id: int, titulo: str = Form(...), descricao: str = Form(""), session: Session = Depends(get_session)
):
    """Só troca o rótulo, não o slug -- é o que mantém propostas futuras da
    IA com a grafia antiga ainda casando com este mesmo assunto."""
    assunto = _get_assunto_or_404(session, assunto_id)
    assunto.titulo = titulo.strip() or assunto.titulo
    assunto.descricao = descricao.strip() or None
    session.commit()
    return RedirectResponse(url=f"/assuntos/{assunto_id}", status_code=303)


@router.post("/{assunto_id}/fundir")
def fundir_assunto(assunto_id: int, target_id: int = Form(...), session: Session = Depends(get_session)):
    _get_assunto_or_404(session, assunto_id)
    _get_assunto_or_404(session, target_id)
    merge_assuntos(session, source_id=assunto_id, target_id=target_id)
    session.commit()
    return RedirectResponse(url=f"/assuntos/{target_id}", status_code=303)


@router.post("/{assunto_id}/vinculos/{link_id}/separar")
def separar_vinculo(
    assunto_id: int,
    link_id: int,
    novo_titulo: str = Form(...),
    session: Session = Depends(get_session),
):
    """A IA fatiou demais ou de menos: pega um vínculo aula<->assunto e
    move pra outro assunto (existente, por título, ou um novo)."""
    link = session.get(LessonAssunto, link_id)
    if link is None or link.assunto_id != assunto_id:
        raise HTTPException(status_code=404, detail="vínculo não encontrado")

    lesson = session.get(Lesson, link.lesson_id)
    novo_assunto = find_or_create_assunto(session, novo_titulo)
    ensure_cobertura(session, novo_assunto.id, lesson.subject_id, origem="manual")
    link.assunto_id = novo_assunto.id
    session.commit()
    return RedirectResponse(url=f"/assuntos/{assunto_id}", status_code=303)
