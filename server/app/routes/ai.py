"""Rotas de IA e aprovação (PLANO.md, fase 6): processar (automático ou
manual), aula editada, e a tela de aprovação de cards/datas."""

import html
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
from ..assuntos import ensure_cobertura, find_or_create_assunto, normalize_slug, similar_slugs
from ..auth import require_session
from ..db import get_session
from ..glossary.index import load_active_variants
from ..glossary.merge import find_or_create_term
from ..glossary.render import highlight_html
from ..models import (
    AnnouncementProposal,
    Assunto,
    CardProposal,
    Definition,
    EditedBlock,
    Lesson,
    LessonAssunto,
    Term,
    TermAlias,
)
from ..study.cloze import CLOZE_TIPOS, render_cloze_html, select_blanks

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
    # Modo estudo (fase 8b): só ditado/conceito ganham lacunas -- são os
    # tipos que já carregam sinal de "isso é o que vale a pena decorar".
    cloze_html = {
        block.id: render_cloze_html(block.texto, select_blanks(block.texto))
        for block in blocks
        if block.tipo in CLOZE_TIPOS
    }
    # Glossário (fase 11): marcação em tempo de renderização, nunca
    # gravada no texto (PLANO.md) -- reconstruída a cada request a partir
    # do glossário ativo. `html.escape` primeiro porque `highlight_html`
    # espera HTML já escapado (o texto puro do bloco ainda não é); o modo
    # cloze já entrega HTML pronto, então passa direto.
    variants = load_active_variants(session)
    glossary_html = {
        block.id: highlight_html(cloze_html.get(block.id, html.escape(block.texto)), variants)
        for block in blocks
    }
    return templates.TemplateResponse(
        request,
        "edited_lesson.html",
        {"lesson": lesson, "blocks": blocks, "cloze_html": cloze_html, "glossary_html": glossary_html},
    )


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
        select(CardProposal).where(
            CardProposal.lesson_id == lesson_id, CardProposal.status == "pendente", CardProposal.tipo == "flashcard"
        )
    ).all()
    pairs = session.scalars(
        select(CardProposal).where(
            CardProposal.lesson_id == lesson_id,
            CardProposal.status == "pendente",
            CardProposal.tipo == "discriminacao",
        )
    ).all()
    announcements = session.scalars(
        select(AnnouncementProposal).where(
            AnnouncementProposal.lesson_id == lesson_id, AnnouncementProposal.status == "pendente"
        )
    ).all()
    assuntos = session.scalars(
        select(LessonAssunto).where(LessonAssunto.lesson_id == lesson_id, LessonAssunto.status == "pendente")
    ).all()
    termos = session.scalars(
        select(Definition).where(Definition.lesson_id == lesson_id, Definition.status == "proposto")
    ).all()

    assuntos_por_slug = {a.slug: a for a in session.scalars(select(Assunto))}
    similares_assunto = {
        p.id: [assuntos_por_slug[s] for s in similar_slugs(normalize_slug(p.texto_proposto), list(assuntos_por_slug))]
        for p in assuntos
    }
    termos_por_slug = {t.slug: t for t in session.scalars(select(Term))}
    similares_termo = {
        d.id: [termos_por_slug[s] for s in similar_slugs(normalize_slug(d.termo_proposto), list(termos_por_slug))]
        for d in termos
    }

    return templates.TemplateResponse(
        request,
        "approval.html",
        {
            "lesson": lesson,
            "cards": cards,
            "pairs": pairs,
            "announcements": announcements,
            "assuntos": assuntos,
            "termos": termos,
            "similares_assunto": similares_assunto,
            "similares_termo": similares_termo,
        },
    )


class CardEditBody(BaseModel):
    frente: str
    verso: str


def _activate_card(card: CardProposal) -> None:
    """Aceitar é o que faz o card entrar na fila de revisão (fase 7) — vence
    hoje mesmo, pra não esperar o SM-2 de um card que nunca foi revisado.
    Reaceitar um card descartado antes mantém o agendamento que já tinha."""
    card.status = "aceito"
    if card.due_date is None:
        card.due_date = datetime.now(timezone.utc).date()


@router.post("/{lesson_id}/cards/{card_id}/aceitar")
def accept_card(lesson_id: int, card_id: int, session: Session = Depends(get_session)):
    card = session.get(CardProposal, card_id)
    if card is None or card.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="card não encontrado")
    _activate_card(card)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)


def _accept_all_redirect_url(lesson_id: int, accepted: list[CardProposal]) -> str:
    """Resumo pós-ação + desfazer com escopo: devolve a lista exata de ids
    do lote na própria URL de redirect, sem precisar de flash/sessão. Só
    oferece desfazer quando o lote cabe numa querystring razoável -- acima
    disso o botão de desfazer deixaria de valer o risco de URL gigante."""
    url = f"/lessons/{lesson_id}/aprovacao?aceitos={len(accepted)}"
    if 0 < len(accepted) <= 50:
        ids = ",".join(str(c.id) for c in accepted)
        url += f"&desfazer={ids}"
    return url


@router.post("/{lesson_id}/cards/aceitar-todos")
def accept_all_cards(lesson_id: int, session: Session = Depends(get_session)):
    """PLANO.md: 'há aceitar todos na tela de aprovação' — uma semana
    corrida sem revisar as propostas não pode travar a fila do que já
    está ativo."""
    pending = session.scalars(
        select(CardProposal).where(
            CardProposal.lesson_id == lesson_id, CardProposal.status == "pendente", CardProposal.tipo == "flashcard"
        )
    ).all()
    for card in pending:
        _activate_card(card)
    session.commit()
    return RedirectResponse(url=_accept_all_redirect_url(lesson_id, pending), status_code=303)


@router.post("/{lesson_id}/pares/aceitar-todos")
def accept_all_pairs(lesson_id: int, session: Session = Depends(get_session)):
    """Mesmo botão "aceitar todos" dos cards (PLANO.md), mas pros pares de
    discriminação -- seção própria na aprovação, então "todos" precisa
    significar só os pares, não os cards junto."""
    pending = session.scalars(
        select(CardProposal).where(
            CardProposal.lesson_id == lesson_id,
            CardProposal.status == "pendente",
            CardProposal.tipo == "discriminacao",
        )
    ).all()
    for pair in pending:
        _activate_card(pair)
    session.commit()
    return RedirectResponse(url=_accept_all_redirect_url(lesson_id, pending), status_code=303)


@router.post("/{lesson_id}/cards/desfazer-aceite")
def undo_accept_cards(lesson_id: int, ids: str = Form(""), session: Session = Depends(get_session)):
    """Desfazer do aceitar-todos. Só reverte card ainda não revisado --
    last_reviewed_at is None -- pra nunca rebobinar um estado SM-2 real
    (models.py:324); um card já respondido some da lista de ids devolvida
    pelo redirect, então sequer aparece aqui na prática."""
    try:
        card_ids = [int(i) for i in ids.split(",") if i]
    except ValueError:
        card_ids = []
    cards = session.scalars(
        select(CardProposal).where(
            CardProposal.id.in_(card_ids),
            CardProposal.lesson_id == lesson_id,
            CardProposal.status == "aceito",
            CardProposal.last_reviewed_at.is_(None),
        )
    ).all()
    for card in cards:
        card.status = "pendente"
        card.due_date = None
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao?desfeitos={len(cards)}", status_code=303)


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
    _activate_card(card)
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


@router.post("/{lesson_id}/assuntos/{assunto_proposal_id}/aceitar")
def accept_lesson_assunto(
    lesson_id: int,
    assunto_proposal_id: int,
    titulo: str = Form(""),
    session: Session = Depends(get_session),
):
    """Aceitar resolve/cria o Assunto global pelo slug do título (editável
    aqui antes de aceitar) e registra a cobertura da matéria -- é o ponto
    em que 'Capacidade' de duas aulas diferentes vira o mesmo registro."""
    lesson = _get_lesson_or_404(session, lesson_id)
    proposal = session.get(LessonAssunto, assunto_proposal_id)
    if proposal is None or proposal.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="assunto não encontrado")

    titulo_final = titulo.strip() or proposal.texto_proposto
    ja_existia = session.scalar(select(Assunto.id).where(Assunto.slug == normalize_slug(titulo_final))) is not None
    assunto = find_or_create_assunto(session, titulo_final)
    ensure_cobertura(session, assunto.id, lesson.subject_id, origem="ia")

    proposal.assunto_id = assunto.id
    proposal.status = "aceito"
    session.commit()
    novo = 0 if ja_existia else 1
    return RedirectResponse(
        url=f"/lessons/{lesson_id}/aprovacao?assunto_aceito={_url_escape(titulo_final)}&novo={novo}",
        status_code=303,
    )


@router.post("/{lesson_id}/assuntos/{assunto_proposal_id}/descartar")
def discard_lesson_assunto(lesson_id: int, assunto_proposal_id: int, session: Session = Depends(get_session)):
    proposal = session.get(LessonAssunto, assunto_proposal_id)
    if proposal is None or proposal.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="assunto não encontrado")
    proposal.status = "descartado"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)


@router.post("/{lesson_id}/termos/{definition_id}/aceitar")
def accept_lesson_termo(
    lesson_id: int,
    definition_id: int,
    termo: str = Form(""),
    session: Session = Depends(get_session),
):
    """Aceitar resolve/cria o Term global pelo slug da grafia (editável
    aqui antes de aceitar, igual ao assunto) e aplica as variantes que a
    IA propôs como TermAlias -- é o ponto em que "posse" de duas aulas
    diferentes vira o mesmo verbete."""
    definition = session.get(Definition, definition_id)
    if definition is None or definition.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="termo não encontrado")

    termo_final = termo.strip() or definition.termo_proposto
    ja_existia = session.scalar(select(Term.id).where(Term.slug == normalize_slug(termo_final))) is not None
    term = find_or_create_term(session, termo_final)

    existing_aliases = {a.alias for a in term.aliases} | {term.rotulo}
    variantes = json.loads(definition.variantes_propostas_json) if definition.variantes_propostas_json else []
    # A própria grafia proposta também vira alias quando difere do rótulo do
    # termo -- sem isso, juntar "Negócios jurídicos" em "Negócio jurídico"
    # faz aquela grafia parar de casar no texto da aula (glossary/render.py),
    # perdendo a paridade que glossary/merge.py::merge_terms já garante.
    if definition.termo_proposto:
        variantes = [*variantes, definition.termo_proposto]
    for variante in variantes:
        variante = variante.strip()
        if not variante or variante in existing_aliases:
            continue
        ja_usada = session.scalar(select(TermAlias.id).where(TermAlias.alias == variante))
        if ja_usada:
            continue
        session.add(TermAlias(term_id=term.id, alias=variante))
        existing_aliases.add(variante)

    definition.term_id = term.id
    definition.status = "ativo"
    session.commit()
    novo = 0 if ja_existia else 1
    return RedirectResponse(
        url=f"/lessons/{lesson_id}/aprovacao?termo_aceito={_url_escape(termo_final)}&novo={novo}",
        status_code=303,
    )


@router.post("/{lesson_id}/termos/{definition_id}/descartar")
def discard_lesson_termo(lesson_id: int, definition_id: int, session: Session = Depends(get_session)):
    definition = session.get(Definition, definition_id)
    if definition is None or definition.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="termo não encontrado")
    definition.status = "descartado"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/aprovacao", status_code=303)
