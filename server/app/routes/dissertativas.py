"""Dissertativa avaliada (PLANO.md, fase 13): gerar questão a partir de
uma aula ou de um assunto, responder, corrigir -- ponte manual em ambas
as passadas de IA, como o resto do app."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.budget import BudgetExceededError
from ..ai.client import get_ai_client
from ..ai.dissertativa import (
    ProcessingError,
    build_context_for_lesson,
    build_correction_prompt,
    build_generation_prompt,
    correct_attempt_automatically,
    generate_question_automatically,
    ingest_correction_manual_response,
    ingest_question_manual_response,
    package_correction_as_markdown,
    package_generation_as_markdown,
)
from ..auth import require_session
from ..context.window import build_context_for_assunto
from ..db import get_session
from ..models import Assunto, DissertativaAttempt, DissertativaQuestion, Lesson

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


def _get_lesson_or_404(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    return lesson


def _get_assunto_or_404(session: Session, assunto_id: int) -> Assunto:
    assunto = session.get(Assunto, assunto_id)
    if assunto is None:
        raise HTTPException(status_code=404, detail="assunto não encontrado")
    return assunto


def _get_question_or_404(session: Session, question_id: int) -> DissertativaQuestion:
    question = session.get(DissertativaQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="questão não encontrada")
    return question


def _get_attempt_or_404(session: Session, question_id: int, attempt_id: int) -> DissertativaAttempt:
    attempt = session.get(DissertativaAttempt, attempt_id)
    if attempt is None or attempt.question_id != question_id:
        raise HTTPException(status_code=404, detail="tentativa não encontrada")
    return attempt


# --- geração a partir de uma aula ------------------------------------------------


@router.post("/lessons/{lesson_id}/dissertativas/gerar")
def generate_from_lesson_automatically(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        source_text = build_context_for_lesson(lesson)
        client = get_ai_client()
        question, _ = generate_question_automatically(
            session, subject_id=lesson.subject_id, lesson_id=lesson.id, assunto_id=None,
            source_label=f"Aula: {lesson.titulo}", source_text=source_text, ai_client=client,
        )
    except (ProcessingError, BudgetExceededError, RuntimeError) as exc:
        return RedirectResponse(url=f"/lessons/{lesson_id}?erro_ia={_url_escape(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/dissertativas/{question.id}", status_code=303)


@router.get("/lessons/{lesson_id}/dissertativas/gerar-pacote.md")
def download_generation_package_from_lesson(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        source_text = build_context_for_lesson(lesson)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    source_label = f"Aula: {lesson.titulo}"
    prompt = build_generation_prompt(source_label, source_text)
    content = package_generation_as_markdown(source_label, prompt)
    filename = f"gerar-dissertativa-aula-{lesson_id}.md"
    return PlainTextResponse(
        content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/lessons/{lesson_id}/dissertativas/colar-questao")
def paste_question_form_from_lesson(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    return templates.TemplateResponse(
        request, "dissertativa_paste_question.html",
        {"voltar_url": f"/lessons/{lesson_id}", "action_url": f"/lessons/{lesson_id}/dissertativas/colar-questao"},
    )


@router.post("/lessons/{lesson_id}/dissertativas/colar-questao")
def paste_question_submit_from_lesson(lesson_id: int, resposta: str = Form(...), session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        question, _ = ingest_question_manual_response(
            session, subject_id=lesson.subject_id, lesson_id=lesson.id, assunto_id=None, pasted_text=resposta,
        )
    except (ProcessingError, ValueError) as exc:
        return RedirectResponse(
            url=f"/lessons/{lesson_id}/dissertativas/colar-questao?erro={_url_escape(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/dissertativas/{question.id}", status_code=303)


# --- geração a partir de um assunto ----------------------------------------------


@router.post("/assuntos/{assunto_id}/dissertativas/gerar")
def generate_from_assunto_automatically(assunto_id: int, session: Session = Depends(get_session)):
    assunto = _get_assunto_or_404(session, assunto_id)
    source_text = build_context_for_assunto(session, assunto_id)
    if not source_text:
        return RedirectResponse(
            url=f"/assuntos/{assunto_id}?erro_ia={_url_escape('nenhuma aula aceita vinculada a este assunto ainda')}",
            status_code=303,
        )
    try:
        client = get_ai_client()
        question, _ = generate_question_automatically(
            session, subject_id=None, lesson_id=None, assunto_id=assunto.id,
            source_label=f"Assunto: {assunto.titulo}", source_text=source_text, ai_client=client,
        )
    except (ProcessingError, BudgetExceededError, RuntimeError) as exc:
        return RedirectResponse(url=f"/assuntos/{assunto_id}?erro_ia={_url_escape(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/dissertativas/{question.id}", status_code=303)


@router.get("/assuntos/{assunto_id}/dissertativas/gerar-pacote.md")
def download_generation_package_from_assunto(assunto_id: int, session: Session = Depends(get_session)):
    assunto = _get_assunto_or_404(session, assunto_id)
    source_text = build_context_for_assunto(session, assunto_id)
    if not source_text:
        raise HTTPException(status_code=400, detail="nenhuma aula aceita vinculada a este assunto ainda")
    source_label = f"Assunto: {assunto.titulo}"
    prompt = build_generation_prompt(source_label, source_text)
    content = package_generation_as_markdown(source_label, prompt)
    filename = f"gerar-dissertativa-assunto-{assunto_id}.md"
    return PlainTextResponse(
        content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/assuntos/{assunto_id}/dissertativas/colar-questao")
def paste_question_form_from_assunto(request: Request, assunto_id: int, session: Session = Depends(get_session)):
    _get_assunto_or_404(session, assunto_id)
    return templates.TemplateResponse(
        request, "dissertativa_paste_question.html",
        {"voltar_url": f"/assuntos/{assunto_id}", "action_url": f"/assuntos/{assunto_id}/dissertativas/colar-questao"},
    )


@router.post("/assuntos/{assunto_id}/dissertativas/colar-questao")
def paste_question_submit_from_assunto(assunto_id: int, resposta: str = Form(...), session: Session = Depends(get_session)):
    assunto = _get_assunto_or_404(session, assunto_id)
    try:
        question, _ = ingest_question_manual_response(
            session, subject_id=None, lesson_id=None, assunto_id=assunto.id, pasted_text=resposta,
        )
    except (ProcessingError, ValueError) as exc:
        return RedirectResponse(
            url=f"/assuntos/{assunto_id}/dissertativas/colar-questao?erro={_url_escape(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/dissertativas/{question.id}", status_code=303)


# --- lista, detalhe, responder, corrigir -----------------------------------------


@router.get("/dissertativas")
def list_questions(request: Request, session: Session = Depends(get_session)):
    questions = session.scalars(select(DissertativaQuestion).order_by(DissertativaQuestion.criado_em.desc())).all()
    return templates.TemplateResponse(request, "dissertativas.html", {"questions": questions})


@router.get("/dissertativas/{question_id}")
def question_detail(request: Request, question_id: int, session: Session = Depends(get_session)):
    question = _get_question_or_404(session, question_id)
    attempts = session.scalars(
        select(DissertativaAttempt)
        .where(DissertativaAttempt.question_id == question_id)
        .order_by(DissertativaAttempt.criado_em.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "dissertativa_detail.html",
        {
            "question": question,
            "rubrica": json.loads(question.rubrica_json),
            "attempts": attempts,
            "attempts_context": [
                {
                    "attempt": a,
                    "pontos_cobertos": json.loads(a.pontos_cobertos_json) if a.pontos_cobertos_json else [],
                    "pontos_faltantes": json.loads(a.pontos_faltantes_json) if a.pontos_faltantes_json else [],
                }
                for a in attempts
            ],
        },
    )


@router.post("/dissertativas/{question_id}/responder")
def submit_attempt(question_id: int, resposta_texto: str = Form(...), session: Session = Depends(get_session)):
    _get_question_or_404(session, question_id)
    attempt = DissertativaAttempt(question_id=question_id, resposta_texto=resposta_texto.strip())
    session.add(attempt)
    session.commit()
    return RedirectResponse(url=f"/dissertativas/{question_id}#tentativa-{attempt.id}", status_code=303)


@router.post("/dissertativas/{question_id}/attempts/{attempt_id}/avaliar")
def evaluate_attempt_automatically(question_id: int, attempt_id: int, session: Session = Depends(get_session)):
    attempt = _get_attempt_or_404(session, question_id, attempt_id)
    try:
        client = get_ai_client()
        correct_attempt_automatically(session, attempt, client)
    except (ProcessingError, BudgetExceededError, RuntimeError) as exc:
        return RedirectResponse(
            url=f"/dissertativas/{question_id}?erro_ia={_url_escape(str(exc))}#tentativa-{attempt_id}",
            status_code=303,
        )
    return RedirectResponse(url=f"/dissertativas/{question_id}#tentativa-{attempt_id}", status_code=303)


@router.get("/dissertativas/{question_id}/attempts/{attempt_id}/prompt.md")
def download_correction_package(question_id: int, attempt_id: int, session: Session = Depends(get_session)):
    question = _get_question_or_404(session, question_id)
    attempt = _get_attempt_or_404(session, question_id, attempt_id)
    prompt = build_correction_prompt(question, attempt.resposta_texto)
    content = package_correction_as_markdown(question, prompt)
    filename = f"corrigir-dissertativa-{attempt_id}.md"
    return PlainTextResponse(
        content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/dissertativas/{question_id}/attempts/{attempt_id}/colar-correcao")
def paste_correction_form(request: Request, question_id: int, attempt_id: int, session: Session = Depends(get_session)):
    question = _get_question_or_404(session, question_id)
    attempt = _get_attempt_or_404(session, question_id, attempt_id)
    return templates.TemplateResponse(
        request, "dissertativa_paste_correction.html", {"question": question, "attempt": attempt}
    )


@router.post("/dissertativas/{question_id}/attempts/{attempt_id}/colar-correcao")
def paste_correction_submit(
    question_id: int, attempt_id: int, resposta: str = Form(...), session: Session = Depends(get_session)
):
    attempt = _get_attempt_or_404(session, question_id, attempt_id)
    try:
        ingest_correction_manual_response(session, attempt, resposta)
    except (ProcessingError, ValueError) as exc:
        return RedirectResponse(
            url=f"/dissertativas/{question_id}/attempts/{attempt_id}/colar-correcao?erro={_url_escape(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/dissertativas/{question_id}#tentativa-{attempt_id}", status_code=303)
