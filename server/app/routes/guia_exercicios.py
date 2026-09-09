""""Dominar o guia" (PLANO.md): geração de exercícios de memorização a
partir do guia de uma aula, aprovação, e a fila de prática posicional
(study/guia_scheduler.py) -- tudo deliberadamente separado das rotas de
`/revisao` (cards/SM-2)."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
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
from ..models import GuiaExercicio, Lesson, Subject, User
from ..study.guia_scheduler import (
    listar_removidos,
    manual_adjust,
    mastery_percent,
    next_exercicio,
    pool_status,
    remover_exercicio,
    reset_progresso,
    restaurar_exercicio,
    set_mesa_tamanho,
    submit_attempt,
)

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

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


def _flatten_arvore(node: dict, prefix: str = "") -> list[str]:
    if not isinstance(node, dict):
        return []
    lines = [f"{prefix}{node.get('rotulo', '')}"]
    for filho in node.get("filhos", []) or []:
        lines.extend(_flatten_arvore(filho, prefix + "— "))
    return lines


def _gabarito_lines(tipo: str, gabarito: dict) -> list[str]:
    if tipo == "definicao":
        return [gabarito.get("resposta", "")]
    if tipo == "cloze":
        respostas = gabarito.get("respostas", [])
        # Compat com exercícios gerados antes desta correção, que
        # guardavam a frase com lacuna aqui em vez de em `pergunta`.
        linhas = [gabarito["texto_com_lacunas"]] if gabarito.get("texto_com_lacunas") else []
        if respostas:
            linhas.append("Respostas: " + ", ".join(respostas))
        return linhas
    if tipo == "lista_ordenada":
        return [f"{i + 1}. {item}" for i, item in enumerate(gabarito.get("itens_em_ordem", []))]
    if tipo == "hierarquia":
        return _flatten_arvore(gabarito.get("arvore_alvo", {}))
    if tipo == "discriminacao":
        linhas = [f"{gabarito.get('termo_a', '')} × {gabarito.get('termo_b', '')}"]
        if gabarito.get("eixo"):
            linhas.append(gabarito["eixo"])
        return linhas
    if tipo == "recordacao_livre":
        return gabarito.get("pontos_esperados", [])
    if tipo == "aplicacao_caso":
        linhas = [gabarito.get("caso", "")]
        if gabarito.get("conceito_correto"):
            linhas.append("Conceito correto: " + gabarito["conceito_correto"])
        return linhas
    return [json.dumps(gabarito, ensure_ascii=False)]


# --- escolher aula (hub, a partir de /estudar) -----------------------------------


@router.get("/guia")
def choose_lesson(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    lessons = session.scalars(
        select(Lesson).where(Lesson.guia_titulo.is_not(None)).order_by(Lesson.data.desc())
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
            "gabarito_lines": _gabarito_lines(exercicio.tipo, json.loads(exercicio.gabarito_json)) if exercicio else [],
            "mastery_percent": mastery_percent(session, lesson_id, user.id),
            "pool": pool_status(session, lesson, user.id),
            "removidos": [
                {
                    "exercicio": removido,
                    "gabarito_lines": _gabarito_lines(removido.tipo, json.loads(removido.gabarito_json)),
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


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/ajustar")
def adjust_exercicio(
    lesson_id: int,
    exercicio_id: int,
    delta: int = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    manual_adjust(session, exercicio, user.id, delta)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/remover")
def remover_exercicio_route(
    lesson_id: int,
    exercicio_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    """Tira a questão da fila DESTE usuário -- não descarta pra todo mundo
    (isso é `/exercicios/{id}/descartar`, na tela de aprovação)."""
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    remover_exercicio(session, exercicio, user.id)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/restaurar")
def restaurar_exercicio_route(
    lesson_id: int,
    exercicio_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_session),
):
    exercicio = _get_exercicio_or_404(session, lesson_id, exercicio_id)
    restaurar_exercicio(session, exercicio, user.id)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)


@router.post("/lessons/{lesson_id}/guia/limpar-progresso")
def reset_progresso_route(
    lesson_id: int, session: Session = Depends(get_session), user: User = Depends(require_session)
):
    lesson = _get_lesson_or_404(session, lesson_id)
    reset_progresso(session, lesson, user.id)
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia/praticar", status_code=303)
