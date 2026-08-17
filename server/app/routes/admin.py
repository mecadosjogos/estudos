"""Backup e restauração (PLANO.md, fase 1).

Restaurar é a única operação do sistema que apaga dados de propósito: por isso
sempre mostra uma comparação antes de confirmar, sempre cria uma cópia de
segurança do estado atual, e recusa rodar se houver job de transcrição em
andamento (checagem real entra na fase 4, quando a fila de jobs existir).
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import backup, config
from ..auth import require_session

router = APIRouter(prefix="/admin", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

STAGING_DIR = config.BACKUP_DIR / "staging"


def _job_in_progress() -> bool:
    # A fila de jobs de transcrição só existe a partir da fase 4.
    return False


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
async def stage_restore(request: Request, file: UploadFile = File(...)):
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
            "job_in_progress": _job_in_progress(),
        },
    )


@router.post("/restore/confirm")
def confirm_restore(staged_filename: str = Form(...)):
    if _job_in_progress():
        return RedirectResponse(url="/admin/backups", status_code=303)

    staged_path = STAGING_DIR / staged_filename
    safety_copy = backup.restore_from(staged_path)
    staged_path.unlink(missing_ok=True)
    return RedirectResponse(url=f"/admin/backups?restored_from_safety={safety_copy.name}", status_code=303)
