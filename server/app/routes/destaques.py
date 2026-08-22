"""Destaques em áudio (PLANO.md, fase 15): fila tocável dos momentos
`destaque-prova`/`ditado` das últimas aulas, clipes cortados do mp3 já
comprimido -- "você já ouve aula no ônibus; melhor ouvir 15 minutos de
destaque do que 2 horas de aula inteira"."""

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session
from ..db import get_session
from ..models import EditedBlock, Lesson

router = APIRouter(prefix="/destaques", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

DESTAQUE_TIPOS = ("destaque-prova", "ditado")
LIMIT = 30


def _get_block_or_404(session: Session, block_id: int) -> EditedBlock:
    block = session.get(EditedBlock, block_id)
    if block is None or block.tipo not in DESTAQUE_TIPOS:
        raise HTTPException(status_code=404, detail="destaque não encontrado")
    return block


@router.get("")
def list_destaques(request: Request, session: Session = Depends(get_session)):
    blocks = session.scalars(
        select(EditedBlock)
        .join(Lesson, Lesson.id == EditedBlock.lesson_id)
        .where(EditedBlock.tipo.in_(DESTAQUE_TIPOS), EditedBlock.orfao_em.is_(None))
        .order_by(Lesson.data.desc(), EditedBlock.ordem)
        .limit(LIMIT)
    ).all()
    return templates.TemplateResponse(request, "destaques.html", {"blocks": blocks})


@router.get("/{block_id}/clip.mp3")
def clip_audio(block_id: int, session: Session = Depends(get_session)):
    block = _get_block_or_404(session, block_id)
    lesson = session.get(Lesson, block.lesson_id)
    source_path = config.MEDIA_WEB_DIR / f"lesson-{lesson.id}.mp3"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="áudio da aula não encontrado")

    # A chave do cache inclui start_s/end_s -- se a aula for reprocessada e
    # os limites do bloco mudarem, o clipe velho não é servido por engano.
    span_hash = hashlib.sha256(f"{block.start_s:.2f}-{block.end_s:.2f}".encode()).hexdigest()[:12]
    clip_path = config.DESTAQUES_CLIPS_DIR / f"bloco-{block.id}-{span_hash}.mp3"
    if not clip_path.exists():
        from shared.audio import cut_clip

        cut_clip(source_path, block.start_s, block.end_s, clip_path)

    return FileResponse(clip_path, media_type="audio/mpeg")
