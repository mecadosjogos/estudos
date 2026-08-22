"""Feynman por voz (PLANO.md, fase 13): grava, transcreve (sempre
automático, ASR curto sem custo) e avalia contra a(s) definição(ões) do
termo (ponte manual, como todo o resto de IA do app)."""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..ai.client import get_ai_client
from ..ai.budget import BudgetExceededError
from ..ai.feynman import (
    ProcessingError,
    active_definitions_for_term,
    build_feynman_prompt,
    evaluate_feynman_automatically,
    ingest_feynman_manual_response,
    package_as_markdown,
)
from ..auth import require_session
from ..db import get_session
from ..media.asr import ASRClient, get_asr_client
from ..models import FeynmanAttempt, Term

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


def _get_term_or_404(session: Session, term_id: int) -> Term:
    term = session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="termo não encontrado")
    return term


def _get_attempt_or_404(session: Session, term_id: int, attempt_id: int) -> FeynmanAttempt:
    attempt = session.get(FeynmanAttempt, attempt_id)
    if attempt is None or attempt.term_id != term_id:
        raise HTTPException(status_code=404, detail="tentativa não encontrada")
    return attempt


@router.get("/termos/{term_id}/feynman")
def feynman_record_page(request: Request, term_id: int, session: Session = Depends(get_session)):
    term = _get_term_or_404(session, term_id)
    attempts = session.scalars(
        select(FeynmanAttempt).where(FeynmanAttempt.term_id == term_id).order_by(FeynmanAttempt.criado_em.desc())
    ).all()
    return templates.TemplateResponse(request, "feynman_record.html", {"term": term, "attempts": attempts})


@router.post("/termos/{term_id}/feynman")
def feynman_upload(
    term_id: int,
    audio: UploadFile = File(...),
    session: Session = Depends(get_session),
    asr_client: ASRClient = Depends(get_asr_client),
):
    """Transcrever é sempre automático -- `faster-whisper small` na CPU da
    VPS não é chamada paga, não passa pela ponte manual (PLANO.md)."""
    term = _get_term_or_404(session, term_id)

    config.FEYNMAN_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "gravacao.webm").suffix or ".webm"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest = config.FEYNMAN_AUDIO_DIR / stored_name
    with dest.open("wb") as out:
        out.write(audio.file.read())

    attempt = FeynmanAttempt(term_id=term.id, audio_path=str(dest), status="transcrito")
    try:
        result = asr_client.transcribe(str(dest))
        attempt.transcript_text = result.text
    except Exception as exc:
        attempt.status = "erro"
        attempt.erro = str(exc)
    session.add(attempt)
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}/feynman/{attempt.id}", status_code=303)


@router.get("/termos/{term_id}/feynman/{attempt_id}")
def feynman_attempt_detail(request: Request, term_id: int, attempt_id: int, session: Session = Depends(get_session)):
    term = _get_term_or_404(session, term_id)
    attempt = _get_attempt_or_404(session, term_id, attempt_id)
    definitions = active_definitions_for_term(session, term_id)
    return templates.TemplateResponse(
        request,
        "feynman_attempt.html",
        {
            "term": term,
            "attempt": attempt,
            "definitions": definitions,
            "pontos_cobertos": json.loads(attempt.pontos_cobertos_json) if attempt.pontos_cobertos_json else [],
            "pontos_faltantes": json.loads(attempt.pontos_faltantes_json) if attempt.pontos_faltantes_json else [],
            "divergencias": json.loads(attempt.divergencias_json) if attempt.divergencias_json else [],
        },
    )


@router.post("/termos/{term_id}/feynman/{attempt_id}/avaliar")
def feynman_evaluate_automatically(term_id: int, attempt_id: int, session: Session = Depends(get_session)):
    attempt = _get_attempt_or_404(session, term_id, attempt_id)
    try:
        client = get_ai_client()
        evaluate_feynman_automatically(session, attempt, client)
    except (ProcessingError, BudgetExceededError, RuntimeError) as exc:
        return RedirectResponse(
            url=f"/termos/{term_id}/feynman/{attempt_id}?erro_ia={_url_escape(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/termos/{term_id}/feynman/{attempt_id}", status_code=303)


@router.get("/termos/{term_id}/feynman/{attempt_id}/audio")
def feynman_audio(term_id: int, attempt_id: int, session: Session = Depends(get_session)):
    attempt = _get_attempt_or_404(session, term_id, attempt_id)
    path = Path(attempt.audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="áudio não encontrado")
    return FileResponse(path)


@router.get("/termos/{term_id}/feynman/{attempt_id}/prompt.md")
def feynman_download_prompt(term_id: int, attempt_id: int, session: Session = Depends(get_session)):
    term = _get_term_or_404(session, term_id)
    attempt = _get_attempt_or_404(session, term_id, attempt_id)
    prompt = build_feynman_prompt(term, active_definitions_for_term(session, term_id), attempt.transcript_text or "")
    content = package_as_markdown(term, prompt)
    filename = f"feynman-{attempt_id}.md"
    return PlainTextResponse(
        content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/termos/{term_id}/feynman/{attempt_id}/colar-resposta")
def feynman_paste_form(request: Request, term_id: int, attempt_id: int, session: Session = Depends(get_session)):
    term = _get_term_or_404(session, term_id)
    attempt = _get_attempt_or_404(session, term_id, attempt_id)
    return templates.TemplateResponse(request, "feynman_paste_response.html", {"term": term, "attempt": attempt})


@router.post("/termos/{term_id}/feynman/{attempt_id}/colar-resposta")
def feynman_paste_submit(
    term_id: int, attempt_id: int, resposta: str = Form(...), session: Session = Depends(get_session)
):
    attempt = _get_attempt_or_404(session, term_id, attempt_id)
    try:
        ingest_feynman_manual_response(session, attempt, resposta)
    except (ProcessingError, ValueError) as exc:
        return RedirectResponse(
            url=f"/termos/{term_id}/feynman/{attempt_id}/colar-resposta?erro={_url_escape(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(url=f"/termos/{term_id}/feynman/{attempt_id}", status_code=303)
