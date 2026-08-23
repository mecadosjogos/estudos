"""Backup e restauração (PLANO.md, fase 1).

Restaurar é a única operação do sistema que apaga dados de propósito: por isso
sempre mostra uma comparação antes de confirmar, sempre cria uma cópia de
segurança do estado atual, e recusa rodar se houver job de transcrição em
andamento.
"""

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import backup, config
from ..auth import require_admin
from ..db import get_session
from ..models import Lesson, TranscriptionJob, User
from .jobs import ensure_pending_job

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

STAGING_DIR = config.BACKUP_DIR / "staging"


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


def _job_in_progress(session: Session) -> bool:
    return (
        session.scalar(
            select(TranscriptionJob.id).where(TranscriptionJob.status.in_(["pending", "claimed"])).limit(1)
        )
        is not None
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


@router.get("/seguranca")
def security_panel(request: Request, session: Session = Depends(get_session)):
    pendentes = session.scalars(select(User).where(User.status == "pendente").order_by(User.criado_em)).all()
    usuarios = session.scalars(select(User).where(User.status != "pendente").order_by(User.username)).all()
    return templates.TemplateResponse(
        request, "admin_seguranca.html", {"pendentes": pendentes, "usuarios": usuarios}
    )


@router.post("/seguranca/{user_id}/aprovar")
def aprovar_usuario(
    user_id: int,
    dias: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Serve tanto pra aprovar um cadastro pendente quanto pra conceder
    (ou trocar) acesso temporário num usuário já aprovado -- é a mesma
    mutação (status="aprovado" + expira_em calculado), então uma rota só
    atende os dois botões do painel."""
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/admin/seguranca", status_code=303)
    if user.id == admin.id:
        return RedirectResponse(
            url=f"/admin/seguranca?erro={_url_escape('Você não pode alterar seu próprio acesso.')}",
            status_code=303,
        )
    user.status = "aprovado"
    user.expira_em = datetime.now(timezone.utc) + timedelta(days=int(dias)) if dias.strip() else None
    user.aprovado_por_id = admin.id
    user.decidido_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url="/admin/seguranca", status_code=303)


@router.post("/seguranca/{user_id}/recusar")
def recusar_usuario(
    user_id: int, admin: User = Depends(require_admin), session: Session = Depends(get_session)
):
    user = session.get(User, user_id)
    if user is not None and user.id != admin.id:
        user.status = "recusado"
        user.decidido_em = datetime.now(timezone.utc)
        session.commit()
    return RedirectResponse(url="/admin/seguranca", status_code=303)


@router.post("/seguranca/{user_id}/revogar")
def revogar_usuario(
    user_id: int, admin: User = Depends(require_admin), session: Session = Depends(get_session)
):
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/admin/seguranca", status_code=303)
    if user.id == admin.id:
        return RedirectResponse(
            url=f"/admin/seguranca?erro={_url_escape('Você não pode revogar seu próprio acesso.')}",
            status_code=303,
        )
    user.status = "revogado"
    user.decidido_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url="/admin/seguranca", status_code=303)
