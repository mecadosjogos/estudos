"""Backup e restauração (PLANO.md, fase 1).

Restaurar é a única operação do sistema que apaga dados de propósito: por isso
sempre mostra uma comparação antes de confirmar, sempre cria uma cópia de
segurança do estado atual, e recusa rodar se houver job de transcrição em
andamento.
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import backup, config
from ..ai.budget import month_spend_usd
from ..auth import require_session
from ..db import get_session
from ..models import AiCall, Lesson, TranscriptionJob
from .jobs import ensure_pending_job

router = APIRouter(prefix="/admin", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

STAGING_DIR = config.BACKUP_DIR / "staging"


def _job_in_progress(session: Session) -> bool:
    return (
        session.scalar(
            select(TranscriptionJob.id).where(TranscriptionJob.status.in_(["pending", "claimed"])).limit(1)
        )
        is not None
    )


@router.get("/gasto")
def spend_panel(request: Request, session: Session = Depends(get_session)):
    """Painel de gasto (PLANO.md, fase 8): lê ai_call como fonte única de
    custo. Chamadas manuais sempre entram com custo zero, mas aparecem na
    lista — dá pra ver que o volume de trabalho existe mesmo sem gasto."""
    gasto_mes = month_spend_usd(session)
    calls = session.scalars(select(AiCall).order_by(AiCall.criado_em.desc()).limit(200)).all()
    return templates.TemplateResponse(
        request,
        "admin_gasto.html",
        {
            "gasto_mes": gasto_mes,
            "teto_mensal": config.AI_MONTHLY_BUDGET_USD,
            "calls": calls,
        },
    )


@router.get("/backups")
def list_backups(request: Request):
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(config.BACKUP_DIR.glob("estudos-*.db"), reverse=True)
    return templates.TemplateResponse(request, "admin_backups.html", {"backups": backups})


@router.post("/backups")
def run_backup():
    backup.create_backup()
    return RedirectResponse(url="/admin/backups", status_code=303)


@router.post("/restore/stage")
async def stage_restore(
    request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)
):
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged_path = STAGING_DIR / file.filename
    with staged_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    current_summary = backup.summarize(config.DATABASE_PATH)
    incoming_summary = backup.summarize(staged_path)
    return templates.TemplateResponse(
        request,
        "admin_restore_compare.html",
        {
            "current": current_summary,
            "incoming": incoming_summary,
            "staged_filename": file.filename,
            "job_in_progress": _job_in_progress(session),
        },
    )


@router.post("/restore/confirm")
def confirm_restore(staged_filename: str = Form(...), session: Session = Depends(get_session)):
    blocked = _job_in_progress(session)
    # Fecha antes de restaurar: restore_from precisa derrubar TODAS as conexões
    # do pool (db.maintenance_mode), e esta sessão continuaria aberta até o fim
    # do request se não for liberada agora — no Windows isso chega a travar a
    # troca do arquivo com "em uso por outro processo".
    session.close()
    if blocked:
        return RedirectResponse(url="/admin/backups?restore_blocked=1", status_code=303)

    staged_path = STAGING_DIR / staged_filename
    safety_copy = backup.restore_from(staged_path)
    staged_path.unlink(missing_ok=True)
    return RedirectResponse(url=f"/admin/backups?restored_from_safety={safety_copy.name}", status_code=303)


@router.post("/reconstruir-midia")
def rebuild_media(session: Session = Depends(get_session)):
    """PLANO.md: depois de restaurar um backup, só o banco volta — os mp3
    ficam faltando. Esta ação acha as aulas transcritas sem mp3 no disco e
    enfileira um job `rebuild_media`: o worker recomprime a partir do que
    já tem arquivado localmente, sem baixar nem transcrever nada de novo."""
    lessons = session.scalars(select(Lesson).where(Lesson.transcript.has())).all()
    enqueued = 0
    for lesson in lessons:
        mp3_path = config.MEDIA_WEB_DIR / f"lesson-{lesson.id}.mp3"
        if not mp3_path.exists():
            ensure_pending_job(session, lesson.id, target="rebuild_media")
            enqueued += 1
    return RedirectResponse(url=f"/admin/backups?media_rebuild_enqueued={enqueued}", status_code=303)
