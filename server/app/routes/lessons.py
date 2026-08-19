import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, db
from ..auth import require_session
from ..db import get_session
from ..models import Lesson, Subject, Transcript, TranscriptionJob, TranscriptSegment
from ..transcript_confidence import is_suspicious_segment
from .jobs import claim_job_by_id, ensure_pending_job, ingest_result

router = APIRouter(prefix="/lessons", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/{lesson_id}")
def lesson_detail(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
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
    if lesson.transcript is not None and lesson.transcript.aprovado_em is not None:
        raise HTTPException(
            status_code=409,
            detail="transcrição aprovada — reabra a revisão antes de retranscrever",
        )

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
    if lesson.transcript is not None and lesson.transcript.aprovado_em is not None:
        raise HTTPException(
            status_code=409,
            detail="transcrição aprovada — reabra a revisão antes de retranscrever",
        )

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

    ordered_segments = lesson.transcript.segments  # já vem ordenado por idx (models.py)
    low_confidence_ids = {
        seg.id for i, seg in enumerate(ordered_segments) if is_suspicious_segment(ordered_segments, i)
    }
    segments_json = json.dumps(
        [
            {
                "idx": s.idx, "start_s": s.start_s, "end_s": s.end_s, "text": s.text,
                "low_confidence": s.id in low_confidence_ids,
            }
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
            "low_confidence_ids": low_confidence_ids,
            "has_audio_file": (config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3").exists(),
            "aprovado": lesson.transcript.aprovado_em is not None,
        },
    )


@router.post("/{lesson_id}/transcricao/segments/{segment_id}")
def edit_transcript_segment(
    lesson_id: int, segment_id: int, texto: str = Form(...), session: Session = Depends(get_session)
):
    """Edição inline de um trecho (fase 8): o Whisper erra, e tudo que vem
    depois -- guia, aula editada, cards -- herda o erro se ninguém
    corrigir aqui primeiro. Bloqueado depois de aprovar (reabra a revisão
    pra editar de novo)."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")

    segment = session.get(TranscriptSegment, segment_id)
    if segment is None or segment.transcript_id != lesson.transcript.id:
        raise HTTPException(status_code=404, detail="trecho não encontrado")

    if lesson.transcript.aprovado_em is not None:
        raise HTTPException(
            status_code=409, detail="transcrição aprovada — reabra a revisão antes de editar"
        )

    texto = texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="texto não pode ficar vazio")

    segment.text = texto
    segment.editado_em = datetime.now(timezone.utc)

    # full_text é o que alimenta guia/aula editada/window.py -- sem
    # recompor aqui, a correção fica presa no segmento e nunca chega na IA.
    ordered = sorted(lesson.transcript.segments, key=lambda s: s.idx)
    lesson.transcript.full_text = " ".join(s.text for s in ordered)

    session.commit()
    return {"ok": True, "text": segment.text}


@router.post("/{lesson_id}/transcricao/aprovar")
def approve_transcript(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")
    lesson.transcript.aprovado_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/transcricao", status_code=303)


@router.post("/{lesson_id}/transcricao/reabrir")
def reopen_transcript(lesson_id: int, session: Session = Depends(get_session)):
    """Único jeito de voltar a editar ou retranscrever depois de aprovar —
    de propósito um passo separado e explícito, não algo que outro botão
    faz de lambuja."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")
    lesson.transcript.aprovado_em = None
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/transcricao", status_code=303)


@router.get("/{lesson_id}/transcricao.txt")
def download_transcript_txt(lesson_id: int, session: Session = Depends(get_session)):
    """Texto puro da transcrição, sem timestamp — mesma fonte do
    `scripts/export_transcript.py` (Transcript.full_text), só que pelo
    navegador em vez de `docker compose exec`."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")

    filename = f"transcricao-{lesson_id}.txt"
    return PlainTextResponse(
        lesson.transcript.full_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lesson_id}/guia-pacote.md")
def download_guia_pacote(lesson_id: int, session: Session = Depends(get_session)):
    """Baixa o prompt + transcrição pra colar num chat do Claude (ponte
    manual) — mesmo padrão de pacote.md/colar-resposta da fase 6, mas
    para o guia de aula (mais simples, sem schema)."""
    from ..ai.guia import build_guia_prompt, package_guia_as_markdown

    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=400, detail="aula sem transcrição — transcreva antes")

    prompt = build_guia_prompt(lesson.titulo, lesson.data.isoformat(), lesson.transcript.full_text)
    content = package_guia_as_markdown(lesson.titulo, prompt)
    filename = f"guia-aula-{lesson_id}.md"
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lesson_id}/colar-guia")
def paste_guia_form(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    return templates.TemplateResponse(request, "paste_guia.html", {"lesson": lesson})


@router.post("/{lesson_id}/colar-guia")
def paste_guia_submit(lesson_id: int, resposta: str = Form(...), session: Session = Depends(get_session)):
    from ..ai.guia import parse_guia_response
    from ..models import AiCall

    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")

    try:
        guia_md = parse_guia_response(resposta)
    except ValueError as exc:
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/lessons/{lesson_id}/colar-guia?erro={quote(str(exc))}", status_code=303
        )

    lesson.guia_md = guia_md
    lesson.guia_gerado_em = datetime.now(timezone.utc)
    session.add(AiCall(lesson_id=lesson_id, tipo_acao="guia_aula", via="manual", modelo="manual", custo_usd=0.0))
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia", status_code=303)


@router.get("/{lesson_id}/guia")
def view_guia(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    import markdown as markdown_lib

    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")

    guia_html = markdown_lib.markdown(lesson.guia_md, extensions=["extra"])
    return templates.TemplateResponse(request, "guia.html", {"lesson": lesson, "guia_html": guia_html})


@router.get("/{lesson_id}/guia.md")
def download_guia_md(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")

    filename = f"guia-aula-{lesson_id}.md"
    return PlainTextResponse(
        lesson.guia_md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
