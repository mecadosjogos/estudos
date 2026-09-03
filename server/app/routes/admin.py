"""Backup e restauração (PLANO.md, fase 1).

Restaurar é a única operação do sistema que apaga dados de propósito: por isso
sempre mostra uma comparação antes de confirmar, sempre cria uma cópia de
segurança do estado atual, e recusa rodar se houver job de transcrição em
andamento.
"""

import io
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import backup, config
from ..auth import require_admin
from ..db import get_session
from ..models import Lesson, Subject, TranscriptionJob, User
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


@router.get("/backups/latest.db")
def download_latest_backup():
    """Cliente HTTP externo (scripts/backup_from_vps.py): cria um backup
    fresco e devolve o arquivo direto, sem parâmetro de nome -- não há
    escolha de arquivo, então não há risco de path traversal aqui."""
    path = backup.create_backup()
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.get("/lessons.json")
def list_lessons_json(session: Session = Depends(get_session)):
    """Mesmo consumidor do endpoint acima: scripts/backup_from_vps.py usa
    isto pra saber quais aulas têm mp3 pra baixar. Exclui a matéria LIXO,
    mesmo filtro que jobs.py::enqueue_pending_transcriptions já usa."""
    lessons = session.scalars(
        select(Lesson).join(Subject).where(Subject.sigla != "LIXO").order_by(Lesson.id)
    ).all()
    return JSONResponse(
        [
            {
                "id": lesson.id,
                "titulo": lesson.titulo,
                "subject_sigla": lesson.subject.sigla,
                "has_audio": (config.MEDIA_WEB_DIR / f"lesson-{lesson.id}.mp3").exists(),
            }
            for lesson in lessons
        ]
    )


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Três processos, três máquinas possivelmente diferentes (PLANO.md,
# "Arquitetura") -- cada um baixável separado em /admin/backups pra não
# obrigar quem só quer narração a também baixar o venv de GPU do worker,
# por exemplo. Nunca data-backup/ em nenhum dos três (não copiado na
# imagem em primeiro lugar, não precisa de exclusão especial aqui).

# 1. Transcrição (worker Whisper, precisa de GPU) -- só o que
# worker/main.py importa em runtime (worker + shared) e o requirements.txt
# do server (o venv fica em server\.venv, decisão antiga, mas não precisa
# do código do server em si pra transcrever).
TRANSCRICAO_PACKAGE_PATHS = [
    "scripts/instalar_transcricao.ps1", "scripts/instalar_transcricao.bat",
    "worker", "shared", "server/requirements.txt", ".env.example",
]

# 2. Processar aula (IA via Claude Code, sem GPU) -- server inteiro porque
# o processamento manual lê server/app/ai/ pra montar o mesmo prompt (ver
# RUNBOOK.md), os skills (não .claude inteiro -- resto é sessão local, ver
# .gitignore), os docs que RUNBOOK.md referencia, e os atalhos de raiz que
# o próprio RUNBOOK.md manda usar (disparar-skill.ps1 é a base de
# processar-aulas/transcrever-paginas; iniciar-servidor-testes.bat sobe o
# Docker local que disparar-skill.ps1 confere antes de rodar, caso
# SERVER_URL aponte pra 127.0.0.1 em vez de uma VPS de verdade).
PROCESSAR_AULA_PACKAGE_PATHS = [
    "scripts/instalar_processar_aula.ps1", "scripts/instalar_processar_aula.bat",
    "disparar-skill.ps1", "iniciar-servidor-testes.bat",
    "processar-aulas.ps1", "processar-aulas.bat",
    "transcrever-paginas.ps1", "transcrever-paginas.bat",
    ".claude/skills", "server", "docs",
    "RUNBOOK.md", "PLANO.md", "CLAUDE.md", ".env.example",
]

# 3. Narração (TTS local) -- tts-service/ é standalone de propósito (PLANO.md:
# "API genérica, reusável por qualquer script na máquina"), sem SERVER_URL
# nem credencial nenhuma pra embutir -- por isso não passa por
# _build_deploy_script como os outros dois.
NARRACAO_PACKAGE_PATHS = ["tts-service"]


def _build_deploy_script(request: Request, script_rel_path: str, *, include_access_token: bool) -> str:
    """Um .ps1 de instalação com SERVER_URL (e, quando pedido, ACCESS_TOKEN)
    JÁ deste deploy embutidos -- quem baixa já está autenticado como admin,
    então isso não é uma exposição nova, só evita copiar/colar na hora do
    prompt.

    Lê o esquema/host de X-Forwarded-* primeiro: atrás do Traefik (produção)
    o uvicorn recebe a requisição como HTTP simples do container -- sem
    isso o script baixado apontaria pra http://, não https://.
    """
    script_path = REPO_ROOT / script_rel_path
    content = script_path.read_text(encoding="utf-8")

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    server_url = f"{scheme}://{host}"

    prelude = f'$env:ESTUDOS_SERVER_URL = "{server_url}"\n'
    if include_access_token:
        prelude += f'$env:ESTUDOS_ACCESS_TOKEN = "{config.ACCESS_TOKEN}"\n'
    return content.replace('$ErrorActionPreference = "Stop"\n', '$ErrorActionPreference = "Stop"\n' + prelude, 1)


def _build_install_zip(request: Request, paths: list[str], deploy_script_rel_path: str, *, include_access_token: bool) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in paths:
            path = REPO_ROOT / rel
            if path.is_file():
                if rel == deploy_script_rel_path:
                    continue  # entra abaixo, já com SERVER_URL/ACCESS_TOKEN
                zf.write(path, arcname=rel)
            elif path.is_dir():
                for file_path in path.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(REPO_ROOT).as_posix()
                        if arcname == deploy_script_rel_path:
                            continue
                        zf.write(file_path, arcname=arcname)

        zf.writestr(
            deploy_script_rel_path,
            _build_deploy_script(request, deploy_script_rel_path, include_access_token=include_access_token),
        )

    buffer.seek(0)
    return buffer


@router.get("/instalar-transcricao.ps1")
def download_transcricao_script(request: Request):
    """Só o script, pra quem já tem o repositório clonado numa máquina de
    worker e só quer atualizar SERVER_URL/ACCESS_TOKEN sem baixar tudo de
    novo."""
    content = _build_deploy_script(request, "scripts/instalar_transcricao.ps1", include_access_token=True)
    return PlainTextResponse(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="instalar_transcricao.ps1"'},
    )


@router.get("/instalar-transcricao.zip")
def download_transcricao_package(request: Request):
    """Pra uma máquina de GPU totalmente nova, sem repositório nenhum
    ainda: baixa, extrai, roda o .ps1 de dentro -- self-contained, nem
    precisa de Git nessa máquina (só o que instalar_transcricao.ps1 já
    pressupõe: driver NVIDIA, Python, ffmpeg via winget)."""
    buffer = _build_install_zip(
        request, TRANSCRICAO_PACKAGE_PATHS, "scripts/instalar_transcricao.ps1", include_access_token=True
    )
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="estudos-transcricao-setup.zip"'},
    )


@router.get("/instalar-processar-aula.ps1")
def download_processar_aula_script(request: Request):
    content = _build_deploy_script(request, "scripts/instalar_processar_aula.ps1", include_access_token=False)
    return PlainTextResponse(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="instalar_processar_aula.ps1"'},
    )


@router.get("/instalar-processar-aula.zip")
def download_processar_aula_package(request: Request):
    """Pra uma máquina nova (sem GPU nenhuma -- não precisa) que só vai
    abrir chats do Claude Code pra processar aula/página (RUNBOOK.md)."""
    buffer = _build_install_zip(
        request, PROCESSAR_AULA_PACKAGE_PATHS, "scripts/instalar_processar_aula.ps1", include_access_token=False
    )
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="estudos-processar-aula-setup.zip"'},
    )


@router.get("/instalar-narracao.zip")
def download_narracao_package():
    """tts-service/ puro -- nenhum dado deste deploy pra embutir (serviço
    standalone, ver NARRACAO_PACKAGE_PATHS), então sem variante ".ps1 só".
    Roda na mesma máquina que já tem o worker de transcrição de pé: é o
    modo contínuo dele (worker/run_local.ps1) que drena a fila de narração
    assim que este serviço responde em 127.0.0.1:8100."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in NARRACAO_PACKAGE_PATHS:
            path = REPO_ROOT / rel
            for file_path in path.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.relative_to(REPO_ROOT).as_posix())

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="estudos-narracao-setup.zip"'},
    )


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
