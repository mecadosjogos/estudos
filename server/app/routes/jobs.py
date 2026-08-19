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
from ..models import AudioSegment, Transcript, TranscriptionJob, TranscriptSegment

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


def claim_next_job(session: Session, worker_name: str, target: str) -> TranscriptionJob | None:
    """Reivindica o job pendente mais antigo daquele alvo, ou None se não achar
    nenhum (ou perder a corrida para outro processo). Idempotente em `chamar de
    novo`: um None não significa erro, só "tenta na próxima"."""
    _reclaim_stale(session, target)

    candidate_id = session.scalar(
        select(TranscriptionJob.id)
        .where(TranscriptionJob.target == target, TranscriptionJob.status == "pending")
        .order_by(TranscriptionJob.criado_em)
        .limit(1)
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
    worker_name: str, target: str = "gpu_worker", session: Session = Depends(get_session)
):
    job = claim_next_job(session, worker_name, target)
    if job is None:
        return JSONResponse({"job": None})

    segments = sorted(job.lesson.audio_segments, key=lambda s: s.ordem)
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
