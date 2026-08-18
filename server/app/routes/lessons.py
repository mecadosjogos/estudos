import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, db
from ..auth import require_session
from ..db import get_session
from ..models import Lesson, Subject, TranscriptionJob
from .jobs import claim_job_by_id, ensure_pending_job, ingest_result

router = APIRouter(prefix="/lessons", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/{lesson_id}")
def lesson_detail(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    all_subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    latest_job = session.scalar(
        select(TranscriptionJob)
        .where(TranscriptionJob.lesson_id == lesson_id)
        .order_by(TranscriptionJob.criado_em.desc())
        .limit(1)
    )
    return templates.TemplateResponse(
        request,
        "lesson_detail.html",
        {"lesson": lesson, "all_subjects": all_subjects, "latest_job": latest_job},
    )


@router.post("/{lesson_id}")
def update_lesson(
    lesson_id: int,
    titulo: str = Form(...),
    data: str = Form(...),
    google_doc_url: str = Form(""),
    session: Session = Depends(get_session),
):
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        lesson.titulo = titulo.strip()
        lesson.data = datetime.strptime(data, "%Y-%m-%d").date()
        lesson.google_doc_url = google_doc_url.strip() or None
        session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/move")
def move_lesson(lesson_id: int, subject_id: int = Form(...), session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        # Cards e definições ligados à aula seguem por FK — não há nada para migrar
        # à parte, já que nenhum dos dois carrega subject_id próprio (ver PLANO.md,
        # Integridade #3: matéria não é atributo do trecho).
        lesson.subject_id = subject_id
        session.commit()
    return RedirectResponse(url=f"/subjects/{subject_id}", status_code=303)


@router.post("/{lesson_id}/iniciar-transcricao")
def start_transcription(lesson_id: int, session: Session = Depends(get_session)):
    """Botão manual pra quando a aula tem áudio mas nunca ganhou job — cobre
    tanto o caso raro (upload antigo, de antes do enfileiramento automático)
    quanto o caso comum de reprocessar do zero."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    if not lesson.audio_segments:
        raise HTTPException(status_code=400, detail="aula sem áudio")

    ensure_pending_job(session, lesson_id, target="gpu_worker")
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/transcrever-na-vps")
def transcribe_on_vps(lesson_id: int, session: Session = Depends(get_session)):
    """Válvula de emergência (PLANO.md): quando nenhum worker de GPU está
    ligado, transcreve na própria CPU da VPS com modelo médio — mais lento e
    um pouco pior em termo técnico, mas acionado por você, nunca automático."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    if not lesson.audio_segments:
        raise HTTPException(status_code=400, detail="aula sem áudio")

    job = ensure_pending_job(session, lesson_id, target="vps_cpu")

    threading.Thread(target=_run_vps_cpu_job, args=(job.id,), daemon=True).start()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


def _run_vps_cpu_job(job_id: int) -> None:
    """Roda numa thread separada porque a transcrição em CPU é lenta (minutos
    a dezenas de minutos) e não pode bloquear o loop de eventos do FastAPI.
    Usa sua própria sessão de banco — nunca compartilhar sessão entre threads."""
    from shared.audio import compress_to_mp3, concat_audio_files
    from shared.transcriber import WhisperTranscriber

    session = db.holder.SessionLocal()
    work_dir = config.UPLOAD_STAGING_DIR / f"vps-job-{job_id}"
    try:
        job = claim_job_by_id(session, job_id, worker_name="vps-cpu")
        if job is None:
            return

        segments = sorted(job.lesson.audio_segments, key=lambda s: s.ordem)
        audio_paths = [Path(s.storage_path) for s in segments]

        work_dir.mkdir(parents=True, exist_ok=True)
        concatenated = work_dir / "concatenated.wav"
        concat_audio_files(audio_paths, concatenated)

        transcriber = WhisperTranscriber(
            model_size=config.WHISPER_VPS_MODEL,
            device="cpu",
            compute_type=config.WHISPER_VPS_COMPUTE_TYPE,
        )
        output = transcriber.transcribe(str(concatenated))

        mp3_path = work_dir / "audio.mp3"
        compress_to_mp3(concatenated, mp3_path)

        with mp3_path.open("rb") as f:
            ingest_result(
                session,
                job,
                engine=f"faster-whisper-{config.WHISPER_VPS_MODEL}-cpu",
                worker_name="vps-cpu",
                duration_s=output.duration_s,
                full_text=output.full_text,
                segments=[
                    {
                        "idx": s.idx,
                        "start_s": s.start_s,
                        "end_s": s.end_s,
                        "text": s.text,
                        "words": [
                            {"text": w.text, "start_s": w.start_s, "end_s": w.end_s, "probability": w.probability}
                            for w in s.words
                        ],
                    }
                    for s in output.segments
                ],
                mp3_bytes_iter=iter(lambda: f.read(1024 * 1024), b""),
            )
    except Exception as exc:  # noqa: BLE001 — job de fundo: erro vira status "failed", nunca some silencioso
        job = session.get(TranscriptionJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            session.commit()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        session.close()


@router.get("/{lesson_id}/transcricao")
def lesson_transcript(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    """A leitura de verdade (fase 5): transcrição com player sincronizado —
    tocar um parágrafo pula o áudio, o trecho atual se destaca sozinho."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")

    segments_json = json.dumps(
        [
            {"idx": s.idx, "start_s": s.start_s, "end_s": s.end_s, "text": s.text}
            for s in lesson.transcript.segments
        ]
    )
    return templates.TemplateResponse(
        request,
        "lesson_transcript.html",
        {
            "lesson": lesson,
            "transcript": lesson.transcript,
            "segments_json": segments_json,
            "has_audio_file": (config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3").exists(),
        },
    )


@router.get("/{lesson_id}/audio")
def lesson_audio(lesson_id: int):
    path = config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="áudio não encontrado")
    return FileResponse(path, media_type="audio/mpeg")


class PositionBody(BaseModel):
    posicao_s: float


@router.post("/{lesson_id}/posicao")
def save_position(lesson_id: int, body: PositionBody, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    lesson.posicao_s = max(0.0, body.posicao_s)
    session.commit()
    return {"ok": True}
