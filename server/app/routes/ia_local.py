"""Rotas da IA local (PLANO.md, fase 13b).

`/api/ia-local/*` é o lado da MÁQUINA (ouvinte em worker/ia_local.py, Bearer
ACCESS_TOKEN -- a mesma credencial de máquina do worker de transcrição).
`/ia-local/*` é o lado do NAVEGADOR (sessão): estado da máquina e de um job.
Ver ai/fila_local.py pro desenho do long-poll.
"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai import fila_local
from ..ai.dissertativa import marcar_falha, processar_resultado
from ..auth import require_session, require_session_or_token
from ..db import get_session, holder
from ..models import IaLocalJob

api_router = APIRouter(prefix="/api/ia-local", dependencies=[Depends(require_session_or_token)])
router = APIRouter(prefix="/ia-local", dependencies=[Depends(require_session)])

WAIT_MAXIMO_S = 25.0
# Mesmo com o evento em memória, reconsulta o banco a cada tanto (ver
# ai/fila_local.py: rede de segurança se um dia houver mais de um processo).
INTERVALO_RECONSULTA_S = 1.0


def _job_para_maquina(job: IaLocalJob) -> dict:
    payload = json.loads(job.payload_json)
    return {
        "id": job.id,
        "claim_token": job.claim_token,
        "tipo": job.tipo,
        # Só as chamadas: `meta` é do servidor, o ouvinte não precisa saber.
        "chamadas": payload["chamadas"],
    }


def _tentar_reivindicar(worker_name: str, presenca: dict | None) -> dict | None:
    with holder.SessionLocal() as session:
        if presenca is not None:
            fila_local.registrar_presenca(session, worker_name, **presenca)
        job = fila_local.reivindicar_proximo(session, worker_name)
        return _job_para_maquina(job) if job is not None else None


@api_router.get("/next")
async def next_job(
    worker_name: str,
    wait: float = 0.0,
    motor: str | None = None,
    modelo: str | None = None,
    claude_autorizado_ate: datetime | None = None,
    ocupado_etapa: str | None = None,
):
    """Long-poll: devolve um job assim que houver um, ou `{"job": null}`
    depois de `wait` segundos (máx. 25). Cada chamada também conta como
    "estou ligado" (presença), com o motor e o modelo ativos na máquina."""
    presenca = {
        "motor": motor, "modelo": modelo, "claude_autorizado_ate": claude_autorizado_ate,
        "ocupado_etapa": ocupado_etapa,
    }
    prazo = time.monotonic() + max(0.0, min(wait, WAIT_MAXIMO_S))
    primeira = True
    while True:
        # Limpa ANTES de consultar: um job criado entre a consulta e a
        # espera dispara o evento depois do clear e acorda a espera na hora.
        fila_local.sinal.limpar()
        # Presença uma vez por requisição, não a cada reconsulta do banco.
        job = await run_in_threadpool(_tentar_reivindicar, worker_name, presenca if primeira else None)
        primeira = False
        if job is not None:
            return JSONResponse({"job": job})
        restante = prazo - time.monotonic()
        if restante <= 0:
            return JSONResponse({"job": None})
        await fila_local.sinal.esperar(min(restante, INTERVALO_RECONSULTA_S))


class ProgressoBody(BaseModel):
    claim_token: str
    etapa: str | None = None
    palavras: int | None = None


@api_router.post("/{job_id}/progresso")
def progresso(job_id: int, body: ProgressoBody, session: Session = Depends(get_session)):
    """Também é o heartbeat. 409 = o job não é mais seu (cancelado, ou
    devolvido pra fila por falta de sinal) -- o ouvinte deve abandonar."""
    job = session.get(IaLocalJob, job_id)
    if not fila_local.validar_claim(job, body.claim_token):
        raise HTTPException(status_code=409, detail="claim inválido, expirado ou cancelado")
    job.heartbeat_at = fila_local._agora()
    if body.etapa is not None:
        job.etapa = body.etapa[:200]
    if body.palavras is not None:
        job.palavras = body.palavras
    fila_local.renovar_presenca(session, job.claimed_by)
    session.commit()
    return {"ok": True}


class RespostaChamada(BaseModel):
    id: str
    conteudo: dict


class ResultadoBody(BaseModel):
    claim_token: str
    respostas: list[RespostaChamada]
    motor: str
    modelo: str
    segundos_total: float | None = None
    tokens_por_s: float | None = None
    reparos: int = 0


@api_router.post("/{job_id}/resultado")
def resultado(job_id: int, body: ResultadoBody, session: Session = Depends(get_session)):
    job = session.get(IaLocalJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    # Idempotente: reenviar o mesmo resultado depois de um timeout de rede
    # (mesmo token) não processa duas vezes. Mesmo padrão de jobs.py.
    if job.status in ("done", "failed") and job.claim_token == body.claim_token:
        return JSONResponse({"ok": True, "already_received": True})
    if not fila_local.validar_claim(job, body.claim_token):
        raise HTTPException(status_code=409, detail="claim inválido, expirado ou cancelado")

    respostas = {r.id: r.conteudo for r in body.respostas}
    job.resultado_json = json.dumps({"respostas": respostas, "reparos": body.reparos}, ensure_ascii=False)
    job.motor = body.motor
    job.modelo = body.modelo
    job.segundos_total = body.segundos_total
    job.tokens_por_s = body.tokens_por_s
    session.flush()
    processar_resultado(session, job, respostas)
    return JSONResponse({"ok": True, "already_received": False})


class FalhaBody(BaseModel):
    claim_token: str
    erro: str


@api_router.post("/{job_id}/falha")
def falha(job_id: int, body: FalhaBody, session: Session = Depends(get_session)):
    job = session.get(IaLocalJob, job_id)
    if job is None or job.claim_token != body.claim_token:
        raise HTTPException(status_code=409, detail="claim inválido ou expirado")
    marcar_falha(session, job, body.erro)
    return {"ok": True}


# --- lado do navegador -------------------------------------------------------------


def estado_da_maquina(session: Session) -> dict:
    presenca = fila_local.presenca_atual(session)
    if presenca is None:
        return {"online": False}
    return {
        "online": True,
        "motor": presenca.motor,
        "modelo": presenca.modelo,
        "claude_autorizado_ate": presenca.claude_autorizado_ate.isoformat() if presenca.claude_autorizado_ate else None,
        "ocupado_etapa": presenca.ocupado_etapa,
    }


def estado_do_job(session: Session, job: IaLocalJob) -> dict:
    return {
        "id": job.id,
        "tipo": job.tipo,
        "status": job.status,
        "etapa": job.etapa,
        "palavras": job.palavras,
        "posicao_na_fila": fila_local.posicao_na_fila(session, job),
        "erro": job.erro,
        "question_id": job.question_id,
        "attempt_id": job.attempt_id,
    }


@router.get("/status.json")
def status_maquina(session: Session = Depends(get_session)):
    return estado_da_maquina(session)


@router.get("/jobs/{job_id}/status.json")
def status_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(IaLocalJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return {"job": estado_do_job(session, job), "maquina": estado_da_maquina(session)}


@router.post("/jobs/{job_id}/cancelar")
def cancelar_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(IaLocalJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    if job.status in ("pending", "claimed"):
        job.status = "cancelled"
        job.etapa = "cancelado"
        session.commit()
    return {"ok": True}
