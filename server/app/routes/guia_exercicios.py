""""Dominar o guia" (PLANO.md): geração de exercícios de memorização a
partir do guia de uma aula, aprovação, e a fila de prática posicional
(study/guia_scheduler.py) -- tudo deliberadamente separado das rotas de
`/revisao` (cards/SM-2)."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.budget import BudgetExceededError
from ..ai.client import get_ai_client
from ..ai.guia_exercicios import (
    ProcessingError,
    build_prompt,
    generate_exercicios_automatically,
    ingest_exercicios_manual_response,
    package_as_markdown,
)
from ..auth import require_session
from ..db import get_session
from ..models import GuiaExercicio, Lesson, Subject, TranscriptionJob, User
from ..study.guia_locucao import (
    PARTES,
    audio_em_dia,
    audio_url,
    caminho_audio,
    gabarito_lines,
    itens_pendentes,
    tem_audio_narrado,
    texto_pergunta,
    texto_resposta,
)
from ..study.guia_scheduler import (
    contagem_por_tipo,
    estrelas,
    listar_removidos,
    manual_adjust,
    marcar_ja_sei,
    mastery_percent,
    next_exercicio,
    pool_status,
    remover_exercicio,
    reset_progresso,
    restaurar_exercicio,
    set_mesa_tamanho,
    set_tipos_filtro,
    submit_attempt,
)
from .jobs import ensure_pending_job

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

ROTULOS_TIPO = {
    "definicao": "Definição",
    "cloze": "Lacuna (cloze)",
    "lista_ordenada": "Lista ordenada",
    "hierarquia": "Hierarquia",
    "discriminacao": "Discriminação",
    "recordacao_livre": "Recordação livre",
    "aplicacao_caso": "Aplicação de caso",
}

GRAU_ACERTO_POR_ATALHO = {1: 0.0, 2: 1.0}  # Não lembrei / Lembrei -- "Quase" removido: perdeu sentido com o streak


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


def _get_lesson_or_404(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    return lesson


def _get_exercicio_or_404(session: Session, lesson_id: int, exercicio_id: int) -> GuiaExercicio:
    exercicio = session.get(GuiaExercicio, exercicio_id)
    if exercicio is None or exercicio.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="exercício não encontrado")
    return exercicio


def _locucao_context(exercicio: GuiaExercicio) -> dict:
    """O que a locução da tela precisa da questão atual: a URL do mp3 de
    cada parte (None enquanto o TTS local não narrou) e o texto falado, que
    a voz do navegador lê nesse meio-tempo."""
    return {
        "pergunta_url": audio_url(exercicio, "pergunta"),
        "resposta_url": audio_url(exercicio, "resposta"),
        "pergunta_texto": texto_pergunta(exercicio),
        "resposta_texto": texto_resposta(exercicio),
    }


# --- escolher aula (hub, a partir de /estudar) -----------------------------------


@router.get("/guia")
def choose_lesson(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    # guia_md (e não guia_titulo) é o que a página do guia exige: aulas
    # processadas antes da estruturação têm só o markdown e caíam de fora
    # da lista, mesmo com guia pronto -- ver lessons.py::view_guia.
    lessons = session.scalars(
        select(Lesson).where(Lesson.guia_md.is_not(None)).order_by(Lesson.data.desc())
    ).all()

    por_materia: dict[int, list[dict]] = {}
    for lesson in lessons:
        por_materia.setdefault(lesson.subject_id, []).append(
            {"lesson": lesson, "mastery_percent": mastery_percent(session, lesson.id, user.id)}
        )

    grupos = [{"subject": subject, "lessons_context": por_materia.get(subject.id, [])} for subject in subjects]
    return templates.TemplateResponse(request, "guia_escolher.html", {"grupos": grupos})


# --- geração ------------------------------------------------------------------


@router.post("/lessons/{lesson_id}/guia/exercicios-gerar")
def generate_exercicios_route(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        client = get_ai_client()
        generate_exercicios_automatically(session, lesson, client)
    except (ProcessingError, BudgetExceededError, RuntimeError) as exc:
        return RedirectResponse(url=f"/lessons/{lesson_id}?erro_ia={_url_escape(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/exercicios-aprovacao", status_code=303)


@router.get("/lessons/{lesson_id}/guia/exercicios-pacote.md")
def download_exercicios_package(lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        prompt = build_prompt(lesson)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = package_as_markdown(lesson, prompt)
    filename = f"guia-exercicios-aula-{lesson_id}.md"
    return PlainTextResponse(
        content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/lessons/{lesson_id}/guia/exercicios-colar-resposta")
def paste_exercicios_form(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    return templates.TemplateResponse(
        request, "guia_exercicios_colar.html", {"lesson": lesson}
    )


@router.post("/lessons/{lesson_id}/guia/exercicios-colar-resposta")
def paste_exercicios_submit(lesson_id: int, resposta: str = Form(...), session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    try:
        ingest_exercicios_manual_response(session, lesson, resposta)
    except (ProcessingError, ValueError) as exc:
        return RedirectResponse(
            url=f"/lessons/{lesson_id}/guia/exercicios-colar-resposta?erro={_url_escape(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/exercicios-aprovacao", status_code=303)


# --- aprovação ------------------------------------------------------------------


@router.get("/lessons/{lesson_id}/guia/exercicios-aprovacao")
def approval_screen(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _get_lesson_or_404(session, lesson_id)
    pending = session.scalars(
        select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson_id, GuiaExercicio.status == "pendente")
    ).all()
    return templates.TemplateResponse(
        request, "guia_exercicios_aprovacao.html", {"lesson": lesson, "pending": pending}
    )


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/aceitar")
def accept_exercicio(lesson_id: int, exercicio_id: int, session: Session = Depends(get_session)):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    exercicio.status = "aceito"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/exercicios-aprovacao", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/descartar")
def discard_exercicio(lesson_id: int, exercicio_id: int, session: Session = Depends(get_session)):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    exercicio.status = "descartado"
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/exercicios-aprovacao", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios-aceitar-todos")
def accept_all_exercicios(lesson_id: int, session: Session = Depends(get_session)):
    pending = session.scalars(
        select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson_id, GuiaExercicio.status == "pendente")
    ).all()
    for exercicio in pending:
        exercicio.status = "aceito"
    session.commit()
    return RedirectResponse(
        url=f"/lessons/{lesson_id}/guia/exercicios-aprovacao?aceitos={len(pending)}", status_code=303
    )


# --- prática ----------------------------------------------------------------


@router.get("/lessons/{lesson_id}/guia/praticar")
def practice(
    request: Request, lesson_id: int, session: Session = Depends(get_session), user: User = Depends(require_session)
):
    lesson = _get_lesson_or_404(session, lesson_id)
    exercicio = next_exercicio(session, lesson, user.id)
    return templates.TemplateResponse(
        request,
        "guia_praticar.html",
        {
            "lesson": lesson,
            "exercicio": exercicio,
            "gabarito_lines": gabarito_lines(exercicio.tipo, json.loads(exercicio.gabarito_json)) if exercicio else [],
            "locucao": _locucao_context(exercicio) if exercicio else None,
            "narracao_disponivel": tem_audio_narrado(session, lesson_id),
            "estrelas": estrelas(session, exercicio, user.id) if exercicio else 0,
            "mastery_percent": mastery_percent(session, lesson_id, user.id),
            "pool": pool_status(session, lesson, user.id),
            "tipos": contagem_por_tipo(session, lesson_id, user.id),
            "rotulos_tipo": ROTULOS_TIPO,
            "removidos": [
                {
                    "exercicio": removido,
                    "gabarito_lines": gabarito_lines(removido.tipo, json.loads(removido.gabarito_json)),
                }
                for removido in listar_removidos(session, lesson_id, user.id)
            ],
        },
    )


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/responder")
def answer_exercicio(
    lesson_id: int,
    exercicio_id: int,
    resposta_texto: str = Form(""),
    shortcut: int = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    if shortcut not in GRAU_ACERTO_POR_ATALHO:
        raise HTTPException(status_code=400, detail="atalho inválido — use 1 ou 2")
    submit_attempt(
        session,
        exercicio,
        user.id,
        resposta_texto=resposta_texto.strip() or None,
        grau_acerto=GRAU_ACERTO_POR_ATALHO[shortcut],
    )
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


# --- locução -----------------------------------------------------------------


@router.post("/lessons/{lesson_id}/guia/locucao")
def request_locucao(lesson_id: int, session: Session = Depends(get_session)):
    """Pedido explícito de narrar as questões da aula: se falta áudio em
    alguma, garante um job `tts_exercicios` na fila (o worker com o
    tts-service de pé narra e sobe um a um). A tela de prática NÃO chama
    isto sozinha -- chamava ao ligar a locução, e cada aula aberta virava
    centenas de mp3 na VPS sem ninguém ter pedido. Idempotente: nada
    pendente não cria job."""
    _get_lesson_or_404(session, lesson_id)
    pendentes = len(itens_pendentes(session, lesson_id))
    if pendentes:
        ensure_pending_job(session, lesson_id, target="tts_exercicios")
    return JSONResponse({"pendentes": pendentes})


@router.post("/lessons/{lesson_id}/guia/locucao/cancelar")
def cancel_locucao(lesson_id: int, session: Session = Depends(get_session)):
    """Tira da fila a narração das questões desta aula (pendente ou em
    andamento). Um worker que esteja no meio do lote passa a levar 409 a
    cada áudio que tenta subir e não reenfileira o resto. Os mp3 já
    narrados ficam -- a tela continua tocando esses."""
    _get_lesson_or_404(session, lesson_id)
    jobs = session.scalars(
        select(TranscriptionJob).where(
            TranscriptionJob.lesson_id == lesson_id,
            TranscriptionJob.target == "tts_exercicios",
            TranscriptionJob.status.in_(["pending", "claimed"]),
        )
    ).all()
    for job in jobs:
        # "cancelled", não "failed": a página da aula mostra o último job de
        # qualquer alvo, e "failed" apareceria lá como falha de transcrição.
        job.status = "cancelled"
        job.error = "narração cancelada"
    session.commit()
    return JSONResponse({"cancelados": len(jobs)})


@router.get("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/audio/{parte}.mp3")
def exercicio_audio(lesson_id: int, exercicio_id: int, parte: str, session: Session = Depends(get_session)):
    if parte not in PARTES:
        raise HTTPException(status_code=404, detail="parte inválida")
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    if not audio_em_dia(exercicio, parte):
        raise HTTPException(status_code=404, detail="áudio ainda não narrado (ou desatualizado)")
    return FileResponse(caminho_audio(lesson_id, exercicio_id, parte), media_type="audio/mpeg")


@router.post("/lessons/{lesson_id}/guia/mesa-tamanho")
def set_mesa_tamanho_route(
    lesson_id: int,
    tamanho: int = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    lesson = _get_lesson_or_404(session, lesson_id)
    set_mesa_tamanho(session, lesson, user.id, tamanho)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/tipos-filtro")
def set_tipos_filtro_route(
    lesson_id: int,
    tipos: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    """Filtro de tipos da tela de prática -- chegam só as caixas MARCADAS
    (checkbox desmarcado não é enviado pelo navegador), e o scheduler
    guarda o complemento."""
    lesson = _get_lesson_or_404(session, lesson_id)
    set_tipos_filtro(session, lesson, user.id, tipos)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/ajustar")
def adjust_exercicio(
    lesson_id: int,
    exercicio_id: int,
    delta: int = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    # "↑ já sei" conta como dois "Lembrei"; "↓ mais cedo" só reagenda.
    if delta > 0:
        marcar_ja_sei(session, exercicio, user.id)
    else:
        manual_adjust(session, exercicio, user.id, delta)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/remover")
def remover_exercicio_route(
    lesson_id: int,
    exercicio_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    """Tira a questão da fila DESTE usuário. Se quem remove é admin, ela é
    descartada pra todos os usuários (ver `remover_exercicio`)."""
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    remover_exercicio(session, exercicio, user.id, para_todos=user.papel == "admin")
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/restaurar")
def restaurar_exercicio_route(
    lesson_id: int,
    exercicio_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    restaurar_exercicio(session, exercicio, user.id, para_todos=user.papel == "admin")
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/limpar-progresso")
def reset_progresso_route(
    lesson_id: int, session: Session = Depends(get_session), user: User = Depends(require_session)
):
    lesson = _get_lesson_or_404(session, lesson_id)
    reset_progresso(session, lesson, user.id)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)
