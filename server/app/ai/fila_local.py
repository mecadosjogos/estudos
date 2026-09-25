"""Fila da IA local (PLANO.md, fase 13b).

A máquina com GPU fica ligada e PUXA o trabalho: faz `GET /api/ia-local/next`
e o servidor segura a requisição até ~25 s, respondendo no instante em que
um job é criado. Nada de porta aberta nem túnel -- a VPS nunca inicia
conexão com o PC. Mesmo desenho do worker de transcrição (claim atômico
com `claim_token`, heartbeat, job parado volta pra fila), com duas
diferenças: o job carrega o prompt pronto e volta com a resposta, e a
espera é long-poll em vez de polling a cada 10 s -- quem está do outro
lado é uma pessoa olhando a tela, não uma fila noturna.

O "acordar na hora" é um asyncio.Event em memória: o servidor roda UM
processo uvicorn (server/Dockerfile), então o evento é visto por todas as
requisições. Mesmo assim o long-poll reconsulta o banco a cada segundo --
se um dia houver mais de um processo, o pior caso vira 1 s de atraso, não
um job perdido.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import IaLocalJob, IaLocalPresenca

# Sem heartbeat por esse tempo, o job volta pra fila. Bem menor que os 15
# min da transcrição: o ouvinte manda progresso a cada poucos segundos, e
# alguém está esperando a correção na tela.
STALE_CLAIM_TIMEOUT = timedelta(minutes=2)
# Long-poll dura até ~25 s; com folga pra rede, quem não aparece há 1 min
# está desligado.
PRESENCA_VALIDA = timedelta(seconds=60)
# Correções passam na frente das gerações (alguém esperando o feedback).
TIPOS_CORRECAO = ("dissertativa_julgar", "dissertativa_redigir")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime | None) -> datetime | None:
    # SQLite não guarda tzinfo: o que volta do banco é naive (em UTC).
    # Mesmo idioma de auth.py::get_current_user.
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


class _Sinal:
    """Evento "tem job novo" que acorda o long-poll. Criado preguiçosamente
    no loop que está rodando (o TestClient e o uvicorn têm loops
    diferentes, e um asyncio.Event fica preso ao loop em que esperou pela
    primeira vez). `disparar` é chamado de rotas síncronas, que rodam no
    threadpool -- por isso call_soon_threadsafe."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._evento: asyncio.Event | None = None

    def _evento_do_loop(self) -> asyncio.Event:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._evento is None:
            self._loop = loop
            self._evento = asyncio.Event()
        return self._evento

    def limpar(self) -> None:
        self._evento_do_loop().clear()

    async def esperar(self, timeout: float) -> None:
        evento = self._evento_do_loop()
        try:
            await asyncio.wait_for(evento.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    def disparar(self) -> None:
        loop, evento = self._loop, self._evento
        if loop is None or evento is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(evento.set)


sinal = _Sinal()


def criar_job(
    session: Session,
    *,
    tipo: str,
    chamadas: list[dict],
    meta: dict | None = None,
    lesson_id: int | None = None,
    question_id: int | None = None,
    attempt_id: int | None = None,
    user_id: int | None = None,
    etapa: str = "na fila",
) -> IaLocalJob:
    job = IaLocalJob(
        tipo=tipo,
        payload_json=json.dumps({"chamadas": chamadas, "meta": meta or {}}, ensure_ascii=False),
        lesson_id=lesson_id,
        question_id=question_id,
        attempt_id=attempt_id,
        user_id=user_id,
        etapa=etapa,
    )
    session.add(job)
    session.commit()
    sinal.disparar()
    return job


def _devolver_parados(session: Session) -> None:
    limite = _agora() - STALE_CLAIM_TIMEOUT
    session.execute(
        update(IaLocalJob)
        .where(IaLocalJob.status == "claimed", IaLocalJob.heartbeat_at < limite)
        .values(status="pending", claim_token=None, claimed_by=None, claimed_at=None, heartbeat_at=None,
                etapa="na fila (a máquina parou de responder, voltou pra fila)")
    )
    session.commit()


def reivindicar_proximo(session: Session, worker_name: str) -> IaLocalJob | None:
    """Pega o job pendente mais antigo, ou None. Correção vem antes de
    geração: alguém está esperando a correção na tela, enquanto a geração
    quase sempre é a pré-geração da próxima questão."""
    _devolver_parados(session)
    prioridade = IaLocalJob.tipo.in_(TIPOS_CORRECAO)
    candidato = session.scalar(
        select(IaLocalJob.id)
        .where(IaLocalJob.status == "pending")
        .order_by(prioridade.desc(), IaLocalJob.criado_em, IaLocalJob.id)
        .limit(1)
    )
    if candidato is None:
        return None

    agora = _agora()
    resultado = session.execute(
        update(IaLocalJob)
        .where(IaLocalJob.id == candidato, IaLocalJob.status == "pending")
        .values(status="claimed", claim_token=str(uuid.uuid4()), claimed_by=worker_name, claimed_at=agora,
                heartbeat_at=agora, attempts=IaLocalJob.attempts + 1, etapa="a máquina recebeu")
    )
    session.commit()
    if resultado.rowcount == 0:
        return None  # outro ouvinte ganhou a corrida
    job = session.get(IaLocalJob, candidato)
    session.refresh(job)
    return job


def registrar_presenca(
    session: Session,
    worker_name: str,
    *,
    motor: str | None,
    modelo: str | None,
    claude_autorizado_ate: datetime | None,
    ocupado_etapa: str | None,
) -> None:
    presenca = session.scalar(select(IaLocalPresenca).where(IaLocalPresenca.worker_name == worker_name))
    if presenca is None:
        presenca = IaLocalPresenca(worker_name=worker_name)
        session.add(presenca)
    presenca.visto_em = _agora()
    presenca.motor = motor
    presenca.modelo = modelo
    presenca.claude_autorizado_ate = claude_autorizado_ate
    presenca.ocupado_etapa = ocupado_etapa
    session.commit()


def renovar_presenca(session: Session, worker_name: str | None) -> None:
    """Enquanto processa um job o ouvinte não faz long-poll; o progresso
    (a cada poucos segundos) mantém a máquina aparecendo como ligada."""
    if not worker_name:
        return
    session.execute(
        update(IaLocalPresenca).where(IaLocalPresenca.worker_name == worker_name).values(visto_em=_agora())
    )


def presenca_atual(session: Session) -> IaLocalPresenca | None:
    """O ouvinte visto mais recentemente, se apareceu no último minuto."""
    presenca = session.scalar(select(IaLocalPresenca).order_by(IaLocalPresenca.visto_em.desc()).limit(1))
    if presenca is None:
        return None
    if _naive(presenca.visto_em) < _naive(_agora() - PRESENCA_VALIDA):
        return None
    return presenca


def posicao_na_fila(session: Session, job: IaLocalJob) -> int:
    """Quantos jobs a máquina ainda faz antes deste (0 = é o próximo ou já
    está rodando), na MESMA ordem de `reivindicar_proximo`: o que está
    rodando termina primeiro; depois as correções (por ordem de chegada),
    e só então as gerações."""
    if job.status != "pending":
        return 0

    def contar(*filtros) -> int:
        return session.scalar(select(func.count(IaLocalJob.id)).where(*filtros)) or 0

    antes = (IaLocalJob.criado_em < job.criado_em) | ((IaLocalJob.criado_em == job.criado_em) & (IaLocalJob.id < job.id))
    rodando = contar(IaLocalJob.status == "claimed")
    if job.tipo in TIPOS_CORRECAO:
        return rodando + contar(IaLocalJob.status == "pending", IaLocalJob.tipo.in_(TIPOS_CORRECAO), antes)
    return (
        rodando
        + contar(IaLocalJob.status == "pending", IaLocalJob.tipo.in_(TIPOS_CORRECAO))
        + contar(IaLocalJob.status == "pending", IaLocalJob.tipo.not_in(TIPOS_CORRECAO), antes)
    )


def validar_claim(job: IaLocalJob | None, claim_token: str) -> bool:
    return job is not None and job.status == "claimed" and job.claim_token == claim_token
