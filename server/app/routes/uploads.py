"""Upload do iPad (PLANO.md, fase 3).

Dois caminhos para o mesmo destino final (um `AudioSegment` gravado em
MEDIA_ORIGINAL_DIR): a página `/upload` faz upload em chunks com retomada
automática — essencial porque uma aula de 2h é grande e o Wi-Fi da faculdade
cai — e o Atalho do iOS manda o arquivo inteiro de uma vez pelo botão
Compartilhar, sem UI, por isso aceita o token direto no cabeçalho.
"""

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session, require_session_or_token
from ..db import get_session
from ..models import AudioSegment, Lesson, Subject
from .jobs import ensure_pending_job

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

api_router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

UPLOAD_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


def _safe_upload_id(upload_id: str) -> str:
    if not UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=400, detail="upload_id inválido")
    return upload_id


def _extension_ok(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in config.UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extensão não aceita: {ext or '(nenhuma)'}")
    return ext


def _manifest_path(upload_id: str) -> Path:
    return config.UPLOAD_STAGING_DIR / upload_id / "manifest.json"


def _enqueue_transcription(session: Session, lesson_id: int) -> None:
    """Chamado só quando TODOS os segmentos da aula já terminaram de subir,
    para o worker nunca pegar uma aula com o intervalo faltando."""
    ensure_pending_job(session, lesson_id, target="gpu_worker")


@router.get("/upload")
def upload_page(request: Request, session: Session = Depends(get_session)):
    subjects = session.scalars(
        select(Subject).where(Subject.encerrada_em.is_(None)).order_by(Subject.nome)
    ).all()
    subject_labels = [f"{s.sigla} — {s.nome}" for s in subjects]
    return templates.TemplateResponse(
        request, "upload.html", {"subjects": subjects, "subject_labels": subject_labels}
    )


@api_router.post("/lessons")
def api_create_lesson(
    subject_id: int = Form(...),
    titulo: str = Form(...),
    data: str = Form(...),
    session: Session = Depends(get_session),
):
    lesson = Lesson(
        subject_id=subject_id,
        titulo=titulo.strip(),
        data=datetime.strptime(data, "%Y-%m-%d").date(),
    )
    session.add(lesson)
    session.commit()
    return JSONResponse({"id": lesson.id})


@api_router.post("/uploads/init")
async def init_upload(request: Request):
    body = await request.json()
    upload_id = _safe_upload_id(body["upload_id"])
    filename = body["filename"]
    total_chunks = int(body["total_chunks"])
    _extension_ok(filename)

    upload_dir = config.UPLOAD_STAGING_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(upload_id)
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "lesson_id": body["lesson_id"],
                    "ordem": body["ordem"],
                    "filename": filename,
                    "total_chunks": total_chunks,
                }
            ),
            encoding="utf-8",
        )

    received = sorted(
        int(p.stem.split("-")[1]) for p in upload_dir.glob("chunk-*") if p.is_file()
    )
    return JSONResponse({"received_chunks": received})


@api_router.put("/uploads/{upload_id}/chunks/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request):
    upload_id = _safe_upload_id(upload_id)
    upload_dir = config.UPLOAD_STAGING_DIR / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="upload não iniciado — chame /uploads/init primeiro")

    body = await request.body()
    if len(body) > config.UPLOAD_CHUNK_MAX_BYTES:
        raise HTTPException(status_code=413, detail="chunk maior que o limite")

    chunk_path = upload_dir / f"chunk-{index:06d}"
    chunk_path.write_bytes(body)
    return JSONResponse({"ok": True})


@api_router.post("/uploads/{upload_id}/complete")
def complete_upload(upload_id: str, session: Session = Depends(get_session)):
    upload_id = _safe_upload_id(upload_id)
    manifest_path = _manifest_path(upload_id)
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="upload desconhecido")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    upload_dir = config.UPLOAD_STAGING_DIR / upload_id
    total_chunks = manifest["total_chunks"]

    chunk_paths = [upload_dir / f"chunk-{i:06d}" for i in range(total_chunks)]
    missing = [i for i, p in enumerate(chunk_paths) if not p.exists()]
    if missing:
        raise HTTPException(status_code=409, detail=f"faltam chunks: {missing}")

    ext = _extension_ok(manifest["filename"])
    config.MEDIA_ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    final_path = config.MEDIA_ORIGINAL_DIR / f"{uuid.uuid4()}{ext}"
    with final_path.open("wb") as out:
        for chunk_path in chunk_paths:
            out.write(chunk_path.read_bytes())

    segment = AudioSegment(
        lesson_id=manifest["lesson_id"],
        ordem=manifest["ordem"],
        original_filename=manifest["filename"],
        storage_path=str(final_path.relative_to(config.BASE_DIR)),
        size_bytes=final_path.stat().st_size,
        status="complete",
    )
    session.add(segment)
    session.commit()

    shutil.rmtree(upload_dir)
    return JSONResponse({"ok": True, "segment_id": segment.id})


@api_router.post("/lessons/{lesson_id}/enqueue-transcription")
def enqueue_transcription(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    _enqueue_transcription(session, lesson_id)
    return JSONResponse({"ok": True})


direct_router = APIRouter(prefix="/api", dependencies=[Depends(require_session_or_token)])


@direct_router.post("/uploads/direct")
def upload_direct(
    subject_sigla: str = Form(...),
    titulo: str = Form(...),
    data: str = Form(""),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Recebe o arquivo inteiro de uma vez — usado pelo Atalho do iOS.

    Sem chunking/retomada: o Atalho não tem como implementar essa lógica, então
    isso é para compartilhamentos pontuais, não para a aula de 2h em Wi-Fi ruim
    (para essa, a página /upload é o caminho certo).
    """
    ext = _extension_ok(file.filename)
    subject = session.scalar(select(Subject).where(Subject.sigla == subject_sigla.strip().upper()))
    if subject is None:
        raise HTTPException(status_code=404, detail=f"matéria '{subject_sigla}' não encontrada")

    lesson_date = datetime.strptime(data, "%Y-%m-%d").date() if data else datetime.now().date()
    lesson = Lesson(subject_id=subject.id, titulo=titulo.strip(), data=lesson_date)
    session.add(lesson)
    session.flush()

    config.MEDIA_ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    final_path = config.MEDIA_ORIGINAL_DIR / f"{uuid.uuid4()}{ext}"
    with final_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    segment = AudioSegment(
        lesson_id=lesson.id,
        ordem=1,
        original_filename=file.filename,
        storage_path=str(final_path.relative_to(config.BASE_DIR)),
        size_bytes=final_path.stat().st_size,
        status="complete",
    )
    session.add(segment)
    session.commit()
    _enqueue_transcription(session, lesson.id)
    return JSONResponse({"ok": True, "lesson_id": lesson.id, "segment_id": segment.id})
