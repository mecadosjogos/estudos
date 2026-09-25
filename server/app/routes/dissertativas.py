"""Dissertativas pelo guia (PLANO.md, fase 13b) -- lado do navegador.

A página de prática (`/lessons/{id}/dissertativas`) é uma tela só, que fala
JSON com as rotas abaixo (mesmo padrão de review.html): pede o estado,
envia a resposta, acompanha a correção e abre pistas sem recarregar. Quem
gera e corrige é a IA local (ai/dissertativa.py + ai/fila_local.py).

O que é pedagogia é aplicado AQUI, no servidor, e não só escondido na tela:
os pontos da rubrica que a pessoa não cobriu só saem em etapas (pista ->
seção do guia -> ponto completo), e a versão melhorada só sai depois de uma
reescrita (ou de "desisto", que devolve a questão pra caixa 0).

As questões da fase 13 (transcrição + ponte manual) continuam visíveis, só
leitura, em /dissertativas/{id}.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai import dissertativa as dis
from ..ai.pipeline import ProcessingError
from ..auth import require_session
from ..db import get_session
from ..markdown_render import render_markdown
from ..models import (
    DISSERTATIVA_CONFIANCAS,
    DISSERTATIVA_VEREDITOS,
    DissertativaAttempt,
    DissertativaDiscordancia,
    DissertativaProgresso,
    DissertativaQuestion,
    GuiaSecao,
    IaLocalJob,
    Lesson,
    Subject,
    User,
)
from ..study import dissertativa_scheduler as agenda
from ..ai.fila_local import posicao_na_fila as fila_posicao
from .ia_local import estado_da_maquina, estado_do_job

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

NIVEL_PISTA_MAXIMO = 3  # 1 = pista, 2 = seção do guia, 3 = ponto completo
# Confiança declarada (1..4) como probabilidade, pra comparar com a cobertura.
CONFIANCA_COMO_FRACAO = {1: 0.125, 2: 0.375, 3: 0.625, 4: 0.875}
LIMIAR_DESCALIBRADO = 0.15


def _usuario(request: Request) -> User:
    return request.state.user


def _lesson_or_404(session: Session, lesson_id: int) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    return lesson


def _question_or_404(session: Session, question_id: int) -> DissertativaQuestion:
    question = session.get(DissertativaQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="questão não encontrada")
    return question


def _attempt_do_usuario(session: Session, attempt_id: int, user: User) -> DissertativaAttempt:
    attempt = session.get(DissertativaAttempt, attempt_id)
    if attempt is None or (attempt.user_id != user.id and user.papel != "admin"):
        raise HTTPException(status_code=404, detail="tentativa não encontrada")
    return attempt


def _tem_guia(session: Session, lesson_id: int) -> bool:
    return session.scalar(select(func.count(GuiaSecao.id)).where(GuiaSecao.lesson_id == lesson_id)) > 0


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


# --- visões (o que vai pro navegador) -------------------------------------------------


def _visao_questao(session: Session, question: DissertativaQuestion, *, motivo: str) -> dict:
    lesson = question.lesson
    return {
        "id": question.id,
        "enunciado": question.enunciado,
        "criterio_texto": question.criterio_texto,
        "tipo": question.tipo,
        "motivo": motivo,  # "nova" | "revisao" | "escolhida"
        "origem": question.origem,
        "secoes": [{"numero": n, "titulo": s.titulo} for n, s in dis.secoes_fonte(session, question)],
        "total_pontos": len(dis.normalizar_rubrica(question.rubrica_json)),
        "guia_mudou": bool(
            lesson is not None and lesson.guia_gerado_em is not None and question.guia_gerado_em_ref is not None
            and _naive(lesson.guia_gerado_em) != _naive(question.guia_gerado_em_ref)
        ),
        "progresso": None,
    }


def _ultimo_job(session: Session, attempt_id: int) -> IaLocalJob | None:
    return session.scalar(
        select(IaLocalJob).where(IaLocalJob.attempt_id == attempt_id).order_by(IaLocalJob.id.desc()).limit(1)
    )


def _versao(attempt: DissertativaAttempt) -> int:
    n, atual = 1, attempt
    while atual.tentativa_anterior is not None:
        n += 1
        atual = atual.tentativa_anterior
    return n


def _tem_reescrita(session: Session, attempt: DissertativaAttempt) -> bool:
    return session.scalar(
        select(func.count(DissertativaAttempt.id)).where(DissertativaAttempt.tentativa_anterior_id == attempt.id)
    ) > 0


def _modelo_liberado(session: Session, attempt: DissertativaAttempt) -> bool:
    # Já é uma reescrita, já foi reescrita, ou a pessoa desistiu.
    return (
        attempt.tentativa_anterior_id is not None
        or attempt.modelo_revelado_em is not None
        or _tem_reescrita(session, attempt)
    )


def _visao_tentativa(session: Session, attempt: DissertativaAttempt) -> dict:
    question = attempt.question
    numeradas = dict(dis.secoes_fonte(session, question))
    todas = {n: s for n, s in enumerate(dis.secoes_da_aula(session, question.lesson_id), start=1)} if question.lesson_id else {}
    vereditos = json.loads(attempt.vereditos_json or "{}")
    pistas = {int(k): v for k, v in json.loads(attempt.pistas_abertas_json or "{}").items()}
    rubrica = dis.normalizar_rubrica(question.rubrica_json)
    discordados = set(
        session.scalars(
            select(DissertativaDiscordancia.ponto_idx).where(DissertativaDiscordancia.attempt_id == attempt.id)
        ).all()
    )

    pontos = []
    for p in vereditos.get("pontos", []):
        idx = p["idx"]
        nivel = pistas.get(idx, 0)
        coberto = p["veredito"] == "coberto"
        secao = todas.get(p.get("secao")) if p.get("secao") else None
        item = {
            "idx": idx,
            "veredito": p["veredito"],
            "trecho": p.get("trecho", "") if p["veredito"] != "nao_verificado" else "",
            "secao": p.get("secao"),
            "secao_titulo": secao.titulo if secao else None,
            "nivel_pista": NIVEL_PISTA_MAXIMO if coberto else nivel,
            "discordado": idx in discordados,
        }
        # Revelação gradual: o que não foi coberto sai em etapas.
        if coberto or nivel >= 1:
            item["pista"] = rubrica[idx]["pista"] if idx < len(rubrica) else ""
        if (coberto or nivel >= 2) and secao is not None:
            item["secao_html"] = render_markdown(secao.corpo)
        if coberto or nivel >= 3:
            item["ponto"] = p["ponto"]
            item["o_que_falta"] = p.get("o_que_falta", "")
        pontos.append(item)

    estrutura = [
        {"campo": campo, "rotulo": rotulo, **(vereditos.get("estrutura", {}).get(campo) or {"atende": False, "trecho": ""})}
        for campo, rotulo in dis.ROTULOS_ESTRUTURA.items()
    ] if vereditos.get("estrutura") else []

    feedback = None
    sugestoes = []
    if attempt.feedback_json:
        feedback = json.loads(attempt.feedback_json)
        sugestoes = dis.sugestoes_do_feedback(feedback)
        liberado = _modelo_liberado(session, attempt)
        feedback["versao_melhorada_liberada"] = liberado
        if not liberado:
            feedback.pop("versao_melhorada", None)
        for pr in feedback.get("prioridades", []):
            s = todas.get(pr.get("secao")) if pr.get("secao") else None
            pr["secao_titulo"] = s.titulo if s else None
        _esconder_vazamentos(feedback, pistas)
        sugestoes = [
            x if x is not None else "(sugestão escondida até você revelar o ponto)"
            for x in [pr.get("sugestao") for pr in feedback.get("prioridades", [])] + list(feedback.get("demais_sugestoes", []))
        ]

    frac, total, soma = dis.cobertura(attempt.vereditos_json)
    job = _ultimo_job(session, attempt.id) if attempt.status in ("julgando", "redigindo", "erro") else None
    reescrita = attempt.tentativa_anterior_id is not None or _tem_reescrita(session, attempt)
    resposta_certa_aberta = attempt.status == "avaliado" and bool(question.resposta_modelo) and (
        attempt.resposta_certa_vista_em is not None or reescrita
    )
    return {
        "id": attempt.id,
        "question_id": question.id,
        "versao": _versao(attempt),
        "status": attempt.status,
        "erro": attempt.erro,
        "resposta_texto": attempt.resposta_texto,
        "confianca": attempt.confianca,
        "confianca_rotulo": DISSERTATIVA_CONFIANCAS.get(attempt.confianca or 0),
        "autoavaliacao_texto": attempt.autoavaliacao_texto,
        "tentativa_anterior_id": attempt.tentativa_anterior_id,
        "tem_reescrita": _tem_reescrita(session, attempt),
        "job": estado_do_job(session, job) if job is not None else None,
        "cobertura": {"soma": soma, "total": total, "fracao": frac},
        "pontos": pontos,
        "estrutura": estrutura,
        "feedback": feedback,
        "sugestoes": sugestoes,
        "sugestoes_escolhidas": json.loads(attempt.sugestoes_escolhidas_json or "[]"),
        "motor": attempt.motor,
        "modelo": attempt.modelo,
        "segundos_total": attempt.segundos_total,
        "secoes_da_questao": [{"numero": n, "titulo": s.titulo} for n, s in numeradas.items()],
        # Resposta certa (gerada com a questão): depois da correção, atrás de
        # um clique. Abrir antes de reescrever conta como desistência.
        "resposta_certa_existe": attempt.status == "avaliado" and bool(question.resposta_modelo),
        "resposta_certa_sem_custo": reescrita,
        "resposta_certa": question.resposta_modelo if resposta_certa_aberta else None,
        "enunciado": question.enunciado,
        "lesson_id": question.lesson_id,
    }


def _esconder_vazamentos(feedback: dict, pistas: dict[int, int]) -> None:
    """Texto do feedback que entregaria um ponto ainda não revelado sai como
    None + `<campo>_escondido_ponto` (ver ai/dissertativa.py::_marcar_vazamentos)."""
    escondidos = {}
    for chave, idx in (feedback.pop("vazamentos", None) or {}).items():
        if pistas.get(idx, 0) >= NIVEL_PISTA_MAXIMO:
            continue
        if "." in chave:
            lista, i = chave.split(".")
            i = int(i)
            itens = feedback.get(lista, [])
            if i < len(itens):
                if lista == "prioridades":
                    itens[i]["sugestao"] = None
                    itens[i]["sugestao_escondida_ponto"] = idx
                else:
                    itens[i] = None
        else:
            feedback[chave] = None
            escondidos[chave] = idx
    feedback["escondidos"] = escondidos
    feedback["demais_sugestoes"] = [x for x in feedback.get("demais_sugestoes", []) if x is not None]


def _garantir_pre_geracao(session: Session, lesson: Lesson, user: User, *, excluir: set[int]) -> None:
    """Deixa uma questão nova pronta ANTES de a pessoa pedir: gera enquanto
    ela escreve ou lê o feedback, e "próxima questão" já sai na hora."""
    if agenda.questoes_novas(session, user.id, lesson, excluir=excluir):
        return
    if dis.job_de_geracao_ativo(session, lesson.id) is not None:
        return
    try:
        dis.enfileirar_geracao(session, lesson, user_id=user.id)
    except ProcessingError:
        pass


# --- páginas ------------------------------------------------------------------------


@router.get("/dissertativas")
def hub(request: Request, session: Session = Depends(get_session)):
    user = _usuario(request)
    linhas = session.execute(
        select(Lesson, Subject)
        .join(Subject, Subject.id == Lesson.subject_id)
        .where(Lesson.id.in_(select(GuiaSecao.lesson_id)), Subject.sigla != "LIXO")
        .order_by(Subject.nome, Lesson.data.desc())
    ).all()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    por_materia: dict[int, dict] = {}
    for lesson, subject in linhas:
        grupo = por_materia.setdefault(subject.id, {"subject": subject, "aulas": []})
        respondidas = session.scalar(
            select(func.count(func.distinct(DissertativaAttempt.question_id)))
            .join(DissertativaQuestion, DissertativaQuestion.id == DissertativaAttempt.question_id)
            .where(DissertativaAttempt.user_id == user.id, DissertativaQuestion.lesson_id == lesson.id)
        )
        vencidas = session.scalar(
            select(func.count(DissertativaProgresso.id))
            .join(DissertativaQuestion, DissertativaQuestion.id == DissertativaProgresso.question_id)
            .where(
                DissertativaProgresso.user_id == user.id,
                DissertativaQuestion.lesson_id == lesson.id,
                DissertativaProgresso.proxima_revisao_em.is_not(None),
                DissertativaProgresso.proxima_revisao_em <= agora,
            )
        )
        grupo["aulas"].append({"lesson": lesson, "respondidas": respondidas, "vencidas": vencidas})

    legado = session.scalars(
        select(DissertativaQuestion)
        .where(DissertativaQuestion.fonte == "transcricao")
        .order_by(DissertativaQuestion.criado_em.desc())
    ).all()
    return templates.TemplateResponse(
        request, "dissertativas.html",
        {"grupos": list(por_materia.values()), "legado": legado, "maquina": estado_da_maquina(session)},
    )


@router.get("/dissertativas/calibracao")
def calibracao(request: Request, session: Session = Depends(get_session)):
    """Confiança declarada x cobertura real, por matéria. Só a v1 de cada
    ciclo conta: é ela que mede o que você sabia sem ter visto o feedback."""
    user = _usuario(request)
    linhas = session.execute(
        select(DissertativaAttempt, DissertativaQuestion, Subject)
        .join(DissertativaQuestion, DissertativaQuestion.id == DissertativaAttempt.question_id)
        .join(Subject, Subject.id == DissertativaQuestion.subject_id)
        .where(
            DissertativaAttempt.user_id == user.id,
            DissertativaAttempt.status == "avaliado",
            DissertativaAttempt.confianca.is_not(None),
            DissertativaAttempt.tentativa_anterior_id.is_(None),
        )
        .order_by(DissertativaAttempt.criado_em.desc())
    ).all()
    por_materia: dict[int, dict] = {}
    recentes = []
    for attempt, question, subject in linhas:
        frac, total, soma = dis.cobertura(attempt.vereditos_json)
        conf = CONFIANCA_COMO_FRACAO[attempt.confianca]
        g = por_materia.setdefault(subject.id, {"subject": subject, "n": 0, "conf": 0.0, "cob": 0.0})
        g["n"] += 1
        g["conf"] += conf
        g["cob"] += frac
        if len(recentes) < 30:
            recentes.append({
                "attempt": attempt, "question": question, "subject": subject,
                "confianca_rotulo": DISSERTATIVA_CONFIANCAS[attempt.confianca], "conf": conf,
                "cobertura": frac, "soma": soma, "total": total,
            })
    materias = []
    for g in por_materia.values():
        conf, cob = g["conf"] / g["n"], g["cob"] / g["n"]
        vies = conf - cob
        leitura = "calibrado"
        if vies > LIMIAR_DESCALIBRADO:
            leitura = "superconfiante"
        elif vies < -LIMIAR_DESCALIBRADO:
            leitura = "subconfiante"
        materias.append({"subject": g["subject"], "n": g["n"], "conf": conf, "cob": cob, "leitura": leitura})
    return templates.TemplateResponse(
        request, "dissertativa_calibracao.html", {"materias": materias, "recentes": recentes}
    )


@router.get("/dissertativas/{question_id}")
def detalhe(request: Request, question_id: int, session: Session = Depends(get_session)):
    """Histórico, só leitura. Questão do guia abre na tela de prática."""
    question = _question_or_404(session, question_id)
    if question.fonte == "guia" and question.lesson_id is not None:
        return RedirectResponse(url=f"/lessons/{question.lesson_id}/dissertativas?questao={question.id}", status_code=303)
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
            "rubrica": dis.normalizar_rubrica(question.rubrica_json),
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


@router.get("/lessons/{lesson_id}/dissertativas")
def praticar(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = _lesson_or_404(session, lesson_id)
    secoes = [{"numero": n, "titulo": s.titulo} for n, s in enumerate(dis.secoes_da_aula(session, lesson_id), start=1)]
    return templates.TemplateResponse(
        request, "dissertativa_praticar.html",
        {"lesson": lesson, "secoes": secoes, "confiancas": DISSERTATIVA_CONFIANCAS},
    )


# --- JSON da tela de prática -----------------------------------------------------------


@router.get("/lessons/{lesson_id}/dissertativas/estado.json")
def estado(request: Request, lesson_id: int, questao: int | None = None, session: Session = Depends(get_session)):
    user = _usuario(request)
    lesson = _lesson_or_404(session, lesson_id)
    maquina = estado_da_maquina(session)
    if not _tem_guia(session, lesson_id):
        return {"modo": "sem_guia", "maquina": maquina}

    if questao is not None:
        question = _question_or_404(session, questao)
        if question.lesson_id != lesson_id:
            raise HTTPException(status_code=404, detail="questão não é desta aula")
        _garantir_pre_geracao(session, lesson, user, excluir={question.id})
        return {"modo": "questao", "questao": _visao_questao(session, question, motivo="escolhida"), "maquina": maquina}

    # Correção em andamento NÃO prende a tela: ela aparece no painel da fila
    # (fila.json) e a pessoa segue pra próxima questão enquanto a máquina
    # corrige.
    vencida = agenda.questao_vencida(session, user.id, lesson_id)
    if vencida is not None:
        question, progresso = vencida
        visao = _visao_questao(session, question, motivo="revisao")
        visao["progresso"] = {"caixa": progresso.caixa, "dias": agenda.dias_desde_ultima(progresso)}
        _garantir_pre_geracao(session, lesson, user, excluir={question.id})
        return {"modo": "questao", "questao": visao, "maquina": maquina}

    novas = agenda.questoes_novas(session, user.id, lesson)
    if novas:
        _garantir_pre_geracao(session, lesson, user, excluir={novas[0].id})
        return {"modo": "questao", "questao": _visao_questao(session, novas[0], motivo="nova"), "maquina": maquina}

    try:
        job = dis.enfileirar_geracao(session, lesson, user_id=user.id)
    except ProcessingError as exc:
        return {"modo": "sem_guia", "erro": str(exc), "maquina": maquina}
    return {"modo": "gerando", "job": estado_do_job(session, job), "maquina": maquina}


ROTULO_ESTADO_FILA = {
    "na_fila": "na fila de correção",
    "em_correcao": "em correção",
    "corrigida": "corrigida — ver avaliação",
    "erro": "a correção falhou",
}


@router.get("/lessons/{lesson_id}/dissertativas/fila.json")
def fila(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    """O que a máquina tem pra VOCÊ nesta aula: correções (na fila, em
    correção, corrigidas ainda não vistas, e as últimas vistas) e a geração
    da próxima questão. A página consulta enquanto houver algo andando."""
    user = _usuario(request)
    lesson = _lesson_or_404(session, lesson_id)
    tentativas = session.scalars(
        select(DissertativaAttempt)
        .join(DissertativaQuestion, DissertativaQuestion.id == DissertativaAttempt.question_id)
        .where(
            DissertativaAttempt.user_id == user.id,
            DissertativaQuestion.lesson_id == lesson_id,
            DissertativaQuestion.fonte == "guia",
        )
        .order_by(DissertativaAttempt.criado_em.desc())
        .limit(30)
    ).all()

    correcoes, vistas = [], 0
    for a in tentativas:
        if a.status == "avaliado" and a.avaliacao_vista_em is not None:
            vistas += 1
            if vistas > 5:
                continue
        job = _ultimo_job(session, a.id) if a.status in ("julgando", "redigindo") else None
        if a.status == "avaliado":
            estado_item = "corrigida"
        elif a.status == "erro":
            estado_item = "erro"
        elif job is not None and job.status == "claimed":
            estado_item = "em_correcao"
        else:
            estado_item = "na_fila"
        frac, total, soma = dis.cobertura(a.vereditos_json)
        correcoes.append({
            "attempt_id": a.id,
            "question_id": a.question_id,
            "enunciado": a.question.enunciado[:110] + ("…" if len(a.question.enunciado) > 110 else ""),
            "versao": _versao(a),
            "estado": estado_item,
            "rotulo": ROTULO_ESTADO_FILA[estado_item],
            "etapa": job.etapa if job is not None else None,
            "posicao": fila_posicao(session, job) if job is not None and job.status == "pending" else 0,
            "cobertura": {"soma": soma, "total": total} if a.status == "avaliado" else None,
            "vista": a.avaliacao_vista_em is not None,
            "erro": a.erro,
        })

    geracao = None
    job_geracao = dis.job_de_geracao_ativo(session, lesson_id)
    if job_geracao is not None:
        geracao = {
            "estado": "gerando" if job_geracao.status == "claimed" else "na_fila",
            "rotulo": "próxima questão sendo gerada" if job_geracao.status == "claimed" else "próxima questão na fila para ser gerada",
            "etapa": job_geracao.etapa,
            "posicao": fila_posicao(session, job_geracao),
        }
    return {
        "correcoes": correcoes,
        "geracao": geracao,
        "questoes_prontas": len(agenda.questoes_novas(session, user.id, lesson)),
        "maquina": estado_da_maquina(session),
    }


@router.post("/lessons/{lesson_id}/dissertativas/nova.json")
def nova(request: Request, lesson_id: int, secao: int | None = Body(None, embed=True), session: Session = Depends(get_session)):
    """Pede uma questão de uma seção específica (seletor da página)."""
    user = _usuario(request)
    lesson = _lesson_or_404(session, lesson_id)
    try:
        job = dis.enfileirar_geracao(session, lesson, secao_numero=secao, user_id=user.id)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": estado_do_job(session, job)}


@router.get("/lessons/{lesson_id}/dissertativas/pacote-claude.md")
def pacote_claude(lesson_id: int, n: int = 5, session: Session = Depends(get_session)):
    """Pacote da skill /gerar-dissertativas (Claude Code, só quando o
    usuário pede): instruções + guia inteiro + o que já existe + schema."""
    from fastapi.responses import PlainTextResponse

    lesson = _lesson_or_404(session, lesson_id)
    try:
        conteudo = dis.pacote_para_claude(session, lesson, max(1, min(n, 15)))
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(
        conteudo, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="gerar-dissertativas-aula-{lesson_id}.md"'},
    )


@router.post("/lessons/{lesson_id}/dissertativas/importar")
async def importar(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    """Recebe o lote gerado pelo Claude. Corpo = o JSON (ou a resposta com o
    bloco ```json), enviado cru como arquivo (`--data-binary @arquivo`) pra
    acento não se corromper no caminho."""
    lesson = _lesson_or_404(session, lesson_id)
    texto = (await request.body()).decode("utf-8")
    try:
        criadas = dis.importar_lote(session, lesson, texto)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "questoes": [{"id": q.id, "enunciado": q.enunciado} for q in criadas]}


@router.post("/dissertativas/{question_id}/responder.json")
def responder(
    request: Request,
    question_id: int,
    resposta_texto: str = Body(...),
    confianca: int = Body(...),
    autoavaliacao_texto: str | None = Body(None),
    tentativa_anterior_id: int | None = Body(None),
    sugestoes_escolhidas: list[int] | None = Body(None),
    session: Session = Depends(get_session),
):
    user = _usuario(request)
    question = _question_or_404(session, question_id)
    if question.fonte != "guia":
        raise HTTPException(status_code=400, detail="questões antigas (da transcrição) são só leitura")
    texto = resposta_texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="a resposta está vazia")
    if confianca not in DISSERTATIVA_CONFIANCAS:
        raise HTTPException(status_code=400, detail="marque a sua confiança antes de enviar")
    if tentativa_anterior_id is not None:
        anterior = _attempt_do_usuario(session, tentativa_anterior_id, user)
        if anterior.question_id != question.id:
            raise HTTPException(status_code=400, detail="a tentativa anterior é de outra questão")

    attempt = DissertativaAttempt(
        question_id=question.id,
        user_id=user.id,
        resposta_texto=texto,
        status="julgando",
        confianca=confianca,
        autoavaliacao_texto=(autoavaliacao_texto or "").strip() or None,
        tentativa_anterior_id=tentativa_anterior_id,
        sugestoes_escolhidas_json=json.dumps(sugestoes_escolhidas or []),
    )
    session.add(attempt)
    session.flush()
    dis.enfileirar_julgamento(session, attempt)
    if question.lesson is not None:
        _garantir_pre_geracao(session, question.lesson, user, excluir={question.id})
    session.refresh(attempt)
    return {"tentativa": _visao_tentativa(session, attempt), "maquina": estado_da_maquina(session)}


@router.get("/dissertativas/attempts/{attempt_id}.json")
def tentativa(
    request: Request, attempt_id: int, marcar_vista: bool = False, session: Session = Depends(get_session)
):
    attempt = _attempt_do_usuario(session, attempt_id, _usuario(request))
    if marcar_vista and attempt.status == "avaliado" and attempt.avaliacao_vista_em is None:
        attempt.avaliacao_vista_em = datetime.now(timezone.utc)
        session.commit()
    return {"tentativa": _visao_tentativa(session, attempt), "maquina": estado_da_maquina(session)}


@router.post("/dissertativas/attempts/{attempt_id}/resposta-certa")
def abrir_resposta_certa(request: Request, attempt_id: int, session: Session = Depends(get_session)):
    """Abre a resposta certa da questão. Antes de reescrever, conta como
    desistência (a questão volta amanhã): ver a resposta pronta sem ter
    tentado de novo não é lembrar."""
    attempt = _attempt_do_usuario(session, attempt_id, _usuario(request))
    if attempt.status != "avaliado":
        raise HTTPException(status_code=400, detail="a correção ainda não terminou")
    if not attempt.question.resposta_modelo:
        raise HTTPException(status_code=404, detail="esta questão não tem resposta certa guardada")
    reescrita = attempt.tentativa_anterior_id is not None or _tem_reescrita(session, attempt)
    if attempt.resposta_certa_vista_em is None:
        if not reescrita and attempt.user_id is not None:
            agenda.registrar_desistencia(session, attempt.user_id, attempt.question_id)
        attempt.resposta_certa_vista_em = datetime.now(timezone.utc)
        session.commit()
    return {"tentativa": _visao_tentativa(session, attempt)}


@router.post("/dissertativas/attempts/{attempt_id}/pista/{idx}")
def abrir_pista(request: Request, attempt_id: int, idx: int, session: Session = Depends(get_session)):
    attempt = _attempt_do_usuario(session, attempt_id, _usuario(request))
    if attempt.status != "avaliado":
        raise HTTPException(status_code=400, detail="a correção ainda não terminou")
    total = len(json.loads(attempt.vereditos_json or "{}").get("pontos", []))
    if not 0 <= idx < total:
        raise HTTPException(status_code=404, detail="ponto não encontrado")
    pistas = json.loads(attempt.pistas_abertas_json or "{}")
    pistas[str(idx)] = min(NIVEL_PISTA_MAXIMO, int(pistas.get(str(idx), 0)) + 1)
    attempt.pistas_abertas_json = json.dumps(pistas)
    session.commit()
    return {"tentativa": _visao_tentativa(session, attempt)}


@router.post("/dissertativas/attempts/{attempt_id}/revelar-modelo")
def revelar_modelo(
    request: Request, attempt_id: int, desisto: bool = Body(False, embed=True), session: Session = Depends(get_session)
):
    user = _usuario(request)
    attempt = _attempt_do_usuario(session, attempt_id, user)
    if not attempt.feedback_json:
        raise HTTPException(status_code=400, detail="a correção ainda não terminou")
    if not _modelo_liberado(session, attempt):
        if not desisto:
            raise HTTPException(status_code=403, detail="reescreva primeiro — ou use \"desisto, mostrar\"")
        attempt.modelo_revelado_por_desistencia = True
        if attempt.user_id is not None:
            agenda.registrar_desistencia(session, attempt.user_id, attempt.question_id)
    if attempt.modelo_revelado_em is None:
        attempt.modelo_revelado_em = datetime.now(timezone.utc)
    session.commit()
    return {"tentativa": _visao_tentativa(session, attempt)}


@router.post("/dissertativas/attempts/{attempt_id}/discordo")
def discordo(
    request: Request,
    attempt_id: int,
    ponto_idx: int = Body(...),
    veredito_usuario: str = Body(...),
    comentario: str | None = Body(None),
    session: Session = Depends(get_session),
):
    user = _usuario(request)
    attempt = _attempt_do_usuario(session, attempt_id, user)
    pontos = json.loads(attempt.vereditos_json or "{}").get("pontos", [])
    if not 0 <= ponto_idx < len(pontos):
        raise HTTPException(status_code=404, detail="ponto não encontrado")
    if veredito_usuario not in DISSERTATIVA_VEREDITOS:
        raise HTTPException(status_code=400, detail="veredito inválido")
    session.add(DissertativaDiscordancia(
        attempt_id=attempt.id, user_id=user.id, ponto_idx=ponto_idx,
        veredito_modelo=pontos[ponto_idx]["veredito"], veredito_usuario=veredito_usuario,
        comentario=(comentario or "").strip() or None, modelo=attempt.modelo,
    ))
    session.commit()
    return {"tentativa": _visao_tentativa(session, attempt)}


@router.post("/dissertativas/attempts/{attempt_id}/tentar-de-novo")
def tentar_de_novo(request: Request, attempt_id: int, session: Session = Depends(get_session)):
    attempt = _attempt_do_usuario(session, attempt_id, _usuario(request))
    if attempt.status != "erro":
        raise HTTPException(status_code=400, detail="esta tentativa não falhou")
    dis.tentar_de_novo(session, attempt)
    return {"tentativa": _visao_tentativa(session, attempt)}
