"""Fila de transcrição (PLANO.md, fase 4).

Claim atômico: duas chamadas concorrentes a `next_job` só podem ambas "ganhar"
se o SQLite permitisse duas escritas simultâneas mudando o mesmo status — o
WAL com escritor único garante que isso não acontece (a segunda UPDATE roda
depois da primeira já ter commitado, e sua cláusula WHERE deixa de casar).

Idempotência: o resultado carrega o `claim_token` recebido no claim. Reenviar
o mesmo resultado com o mesmo token depois de um timeout de rede é reconhecido
como "já recebido" em vez de duplicar a transcrição.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session_or_token
from ..db import get_session
from ..models import AudioSegment, GuiaSecao, Lesson, Subject, Transcript, TranscriptionJob, TranscriptSegment

router = APIRouter(prefix="/api/jobs", dependencies=[Depends(require_session_or_token)])

STALE_CLAIM_TIMEOUT = timedelta(minutes=15)
RESULT_BATCH_SIZE = 500


def ensure_pending_job(session: Session, lesson_id: int, target: str = "gpu_worker") -> TranscriptionJob:
    """Garante que existe um job pendente para a aula **naquele alvo**, criando
    um se não houver nenhum ativo — idempotente, seguro de chamar várias vezes
    (upload de cada arquivo, botão manual, etc). gpu_worker e vps_cpu são filas
    independentes: uma aula pode ter as duas ao mesmo tempo."""
    existing = session.scalar(
        select(TranscriptionJob).where(
            TranscriptionJob.lesson_id == lesson_id,
            TranscriptionJob.target == target,
            TranscriptionJob.status.in_(["pending", "claimed"]),
        )
    )
    if existing is not None:
        return existing

    job = TranscriptionJob(lesson_id=lesson_id, target=target)
    session.add(job)
    session.commit()
    return job


@router.post("/enqueue-pending-transcriptions")
def enqueue_pending_transcriptions(session: Session = Depends(get_session)):
    """Etapa 0 do RUNBOOK.md, mecânica -- sem IA, sem julgamento: acha aula
    com áudio ainda sem transcrição (fora da matéria LIXO) e enfileira.
    Existe pra um script local chamar sozinho antes de rodar o worker,
    sem precisar de um agente pra fazer uma checagem que é só uma
    consulta no banco."""
    rows = session.execute(
        select(Lesson.id, Lesson.titulo)
        .join(Subject, Subject.id == Lesson.subject_id)
        .where(Lesson.audio_segments.any(), ~Lesson.transcript.has(), Subject.sigla != "LIXO")
    ).all()

    enqueued = []
    for row in rows:
        ensure_pending_job(session, row.id, target="gpu_worker")
        enqueued.append({"lesson_id": row.id, "titulo": row.titulo})

    return JSONResponse({"enqueued": enqueued})


def _reclaim_stale(session: Session, target: str) -> None:
    cutoff = datetime.now(timezone.utc) - STALE_CLAIM_TIMEOUT
    session.execute(
        update(TranscriptionJob)
        .where(TranscriptionJob.target == target)
        .where(TranscriptionJob.status == "claimed")
        .where(TranscriptionJob.heartbeat_at < cutoff)
        .values(status="pending", claim_token=None, claimed_by=None, claimed_at=None, heartbeat_at=None)
    )
    session.commit()


def claim_next_job(
    session: Session, worker_name: str, target: str, lesson_id: int | None = None
) -> TranscriptionJob | None:
    """Reivindica o job pendente mais antigo daquele alvo, ou None se não achar
    nenhum (ou perder a corrida para outro processo). Idempotente em `chamar de
    novo`: um None não significa erro, só "tenta na próxima".

    `lesson_id`, quando informado, restringe a busca àquela aula -- pensado
    pra rodada manual avulsa (`worker/main.py --lesson-id`), quando outras
    aulas podem ter job mais antigo no mesmo alvo e não é isso que quem está
    testando quer pegar (achado real: `--once --target tts_guia` sem esse
    filtro reivindicou a narração de outra aula por engano). Sem `lesson_id`,
    comportamento idêntico a antes."""
    _reclaim_stale(session, target)

    filters = [TranscriptionJob.target == target, TranscriptionJob.status == "pending"]
    if lesson_id is not None:
        filters.append(TranscriptionJob.lesson_id == lesson_id)

    candidate_id = session.scalar(
        select(TranscriptionJob.id).where(*filters).order_by(TranscriptionJob.criado_em).limit(1)
    )
    if candidate_id is None:
        return None

    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    result = session.execute(
        update(TranscriptionJob)
        .where(TranscriptionJob.id == candidate_id, TranscriptionJob.status == "pending")
        .values(
            status="claimed",
            claim_token=token,
            claimed_by=worker_name,
            claimed_at=now,
            heartbeat_at=now,
            attempts=TranscriptionJob.attempts + 1,
        )
    )
    session.commit()
    if result.rowcount == 0:
        # outro processo ganhou a corrida entre o SELECT e o UPDATE
        return None

    return session.get(TranscriptionJob, candidate_id)


def claim_job_by_id(session: Session, job_id: int, worker_name: str) -> TranscriptionJob | None:
    """Como claim_next_job, mas para um job específico — usado pelo caminho de
    emergência da VPS, que já sabe qual job criou e não deve pegar outro."""
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    result = session.execute(
        update(TranscriptionJob)
        .where(TranscriptionJob.id == job_id, TranscriptionJob.status == "pending")
        .values(
            status="claimed",
            claim_token=token,
            claimed_by=worker_name,
            claimed_at=now,
            heartbeat_at=now,
            attempts=TranscriptionJob.attempts + 1,
        )
    )
    session.commit()
    if result.rowcount == 0:
        return None
    return session.get(TranscriptionJob, job_id)


@router.get("/next")
def next_job(
    worker_name: str,
    target: str = "gpu_worker",
    lesson_id: int | None = None,
    session: Session = Depends(get_session),
):
    job = claim_next_job(session, worker_name, target, lesson_id)
    if job is None:
        return JSONResponse({"job": None})

    segments = sorted(job.lesson.audio_segments, key=lambda s: s.ordem)
    guia_secoes = sorted(job.lesson.guia_secoes, key=lambda s: s.ordem)
    return JSONResponse({
        "job": {
            "id": job.id,
            "claim_token": job.claim_token,
            "lesson_id": job.lesson_id,
            "lesson_titulo": job.lesson.titulo,
            "segments": [
                {
                    "id": s.id,
                    "ordem": s.ordem,
                    "filename": s.original_filename,
                    "download_url": f"/api/jobs/{job.id}/segments/{s.id}/download",
                }
                for s in segments
            ],
            # Só usado por jobs target=tts_guia (worker/tts.py) -- vazio pros
            # demais alvos, sem custo extra (a relationship já vem carregada
            # junto da aula).
            "guia_secoes": [
                {"ordem": s.ordem, "titulo": s.titulo, "corpo": s.corpo} for s in guia_secoes
            ],
        }
    })


@router.get("/{job_id}/segments/{segment_id}/download")
def download_segment(job_id: int, segment_id: int, session: Session = Depends(get_session)):
    job = session.get(TranscriptionJob, job_id)
    segment = session.get(AudioSegment, segment_id)
    if job is None or segment is None or segment.lesson_id != job.lesson_id:
        raise HTTPException(status_code=404, detail="segmento não encontrado para este job")

    path = Path(segment.storage_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="original já não está mais na VPS")
    return FileResponse(path, filename=segment.original_filename)


class HeartbeatBody(BaseModel):
    claim_token: str


@router.post("/{job_id}/heartbeat")
def heartbeat(job_id: int, body: HeartbeatBody, session: Session = Depends(get_session)):
    job = session.get(TranscriptionJob, job_id)
    if job is None or job.status != "claimed" or job.claim_token != body.claim_token:
        raise HTTPException(status_code=409, detail="claim inválido ou expirado")
    job.heartbeat_at = datetime.now(timezone.utc)
    session.commit()
    return {"ok": True}


def ingest_result(
    session: Session,
    job: TranscriptionJob,
    *,
    engine: str,
    worker_name: str,
    duration_s: float,
    full_text: str,
    segments: list[dict],
    mp3_bytes_iter,
) -> None:
    """Grava o resultado de uma transcrição. Chamado tanto pelo endpoint HTTP
    (worker remoto) quanto pelo caminho de emergência (mesma máquina)."""
    config.MEDIA_WEB_DIR.mkdir(parents=True, exist_ok=True)
    mp3_path = config.MEDIA_WEB_DIR / f"lesson-{job.lesson_id}.mp3"
    with mp3_path.open("wb") as out:
        for chunk in mp3_bytes_iter:
            out.write(chunk)

    existing = session.scalar(select(Transcript).where(Transcript.lesson_id == job.lesson_id))
    if existing is not None:
        session.delete(existing)
        session.commit()

    transcript = Transcript(
        lesson_id=job.lesson_id,
        engine=engine,
        worker_name=worker_name,
        full_text=full_text,
        duration_s=duration_s,
    )
    session.add(transcript)
    session.flush()

    # Escrita fatiada (Limites operacionais do PLANO.md): commits em lotes em
    # vez de uma transação só cobrindo a aula inteira.
    for i in range(0, len(segments), RESULT_BATCH_SIZE):
        batch = segments[i : i + RESULT_BATCH_SIZE]
        session.bulk_insert_mappings(
            TranscriptSegment,
            [
                {
                    "transcript_id": transcript.id,
                    "idx": s["idx"],
                    "start_s": s["start_s"],
                    "end_s": s["end_s"],
                    "text": s["text"],
                    "words_json": json.dumps(s.get("words", [])),
                }
                for s in batch
            ],
        )
        session.commit()

    job.status = "done"
    session.commit()

    # Ciclo de vida do áudio: original sai da VPS assim que a transcrição existe.
    for seg in job.lesson.audio_segments:
        original = Path(seg.storage_path)
        original.unlink(missing_ok=True)


@router.post("/{job_id}/result")
async def submit_result(
    job_id: int,
    claim_token: str = Form(...),
    worker_name: str = Form(...),
    engine: str = Form(...),
    duration_s: float = Form(...),
    payload: UploadFile = File(...),
    audio: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """`payload` chega como arquivo, não como campo de formulário comum —
    o Starlette limita um campo de formulário a 1MB, e uma aula de ~2h
    facilmente passa disso com timestamp por palavra em milhares de
    segmentos. Só peças com filename escapam desse teto."""
    job = session.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")

    if job.status == "done" and job.claim_token == claim_token:
        return JSONResponse({"ok": True, "already_received": True})

    if job.status != "claimed" or job.claim_token != claim_token:
        raise HTTPException(
            status_code=409, detail="claim inválido ou expirado — outro worker já processou"
        )

    data = json.loads(await payload.read())
    ingest_result(
        session,
        job,
        engine=engine,
        worker_name=worker_name,
        duration_s=duration_s,
        full_text=data["full_text"],
        segments=data["segments"],
        mp3_bytes_iter=iter(lambda: audio.file.read(1024 * 1024), b""),
    )
    return JSONResponse({"ok": True, "already_received": False})


@router.post("/{job_id}/rebuild-result")
async def submit_rebuild_result(
    job_id: int,
    claim_token: str = Form(...),
    audio: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Resultado de um job `rebuild_media` (PLANO.md — 'reconstruir mídia'):
    só o mp3 volta, sem transcrição nova — o original já não existe mais em
    lugar nenhum além do archive/ local do worker, que é de onde ele vem."""
    job = session.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")

    if job.status == "done" and job.claim_token == claim_token:
        return JSONResponse({"ok": True, "already_received": True})

    if job.status != "claimed" or job.claim_token != claim_token:
        raise HTTPException(
            status_code=409, detail="claim inválido ou expirado — outro worker já processou"
        )

    config.MEDIA_WEB_DIR.mkdir(parents=True, exist_ok=True)
    mp3_path = config.MEDIA_WEB_DIR / f"lesson-{job.lesson_id}.mp3"
    with mp3_path.open("wb") as out:
        while chunk := await audio.read(1024 * 1024):
            out.write(chunk)

    job.status = "done"
    session.commit()
    return JSONResponse({"ok": True, "already_received": False})


@router.post("/{job_id}/tts-result")
async def submit_tts_result(
    job_id: int,
    claim_token: str = Form(...),
    timestamps: str = Form(...),
    audio: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Resultado de um job `tts_guia` (narração do guia via TTS local, ver
    tts-service/ e worker/main.py::process_tts_job): **um mp3 só pra aula
    inteira** (não um por seção -- toca contínuo, mesmo padrão do áudio da
    aula gravada), mais `timestamps` (JSON, lista de
    `{"ordem": int, "start_s": float, "end_s": float}`, uma entrada por
    seção que narrou com sucesso -- seção que falhou simplesmente não
    aparece na lista, narração parcial é melhor que nenhuma). Não mexe em
    transcrição nenhuma, só grava o áudio, marca a posição de cada seção e
    marca a narração como em dia (`Lesson.guia_audio_gerado_em`)."""
    job = session.get(TranscriptionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")

    if job.status == "done" and job.claim_token == claim_token:
        return JSONResponse({"ok": True, "already_received": True})

    if job.status != "claimed" or job.claim_token != claim_token:
        raise HTTPException(
            status_code=409, detail="claim inválido ou expirado — outro worker já processou"
        )

    lesson_dir = config.GUIA_AUDIO_DIR / f"lesson-{job.lesson_id}"
    lesson_dir.mkdir(parents=True, exist_ok=True)
    dest = lesson_dir / "guia.mp3"
    with dest.open("wb") as out:
        while chunk := await audio.read(1024 * 1024):
            out.write(chunk)

    marcas = json.loads(timestamps)
    secoes_by_ordem = {s.ordem: s for s in job.lesson.guia_secoes}
    for marca in marcas:
        secao = secoes_by_ordem.get(marca["ordem"])
        if secao is not None:
            secao.audio_start_s = marca["start_s"]
            secao.audio_end_s = marca["end_s"]

    job.lesson.guia_audio_gerado_em = datetime.now(timezone.utc)
    job.status = "done"
    session.commit()
    return JSONResponse({"ok": True, "already_received": False})


class FailBody(BaseModel):
    claim_token: str
    error: str


@router.post("/{job_id}/fail")
def fail_job(job_id: int, body: FailBody, session: Session = Depends(get_session)):
    job = session.get(TranscriptionJob, job_id)
    if job is None or job.claim_token != body.claim_token:
        raise HTTPException(status_code=409, detail="claim inválido ou expirado")
    job.status = "failed"
    job.error = body.error
    session.commit()
    return {"ok": True}
