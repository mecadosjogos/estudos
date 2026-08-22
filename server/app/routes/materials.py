"""Materiais e Google Docs (PLANO.md, fase 9): a tabela `material` é a
fonte única pra tudo que não é áudio. Docs entram sozinhos pela sync;
PDF/foto/texto/link entram por aqui à mão — extração de conteúdo de
PDF/foto (visão) é fase 10, aqui é só cadastro + tipo + tag + vínculo.
"""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session
from ..db import get_session
from ..library.gdocs import get_drive_client, sync_drive_folder
from ..models import Material, MaterialTag, MaterialTipo, MaterialUse, Subject

router = APIRouter(prefix="/materials", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


def _get_material_or_404(session: Session, material_id: int) -> Material:
    material = session.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="material não encontrado")
    return material


@router.get("")
def list_materials(request: Request, session: Session = Depends(get_session)):
    materials = session.scalars(select(Material).order_by(Material.criado_em.desc())).all()
    unlinked = [m for m in materials if not m.uses]
    tipos = session.scalars(select(MaterialTipo).order_by(MaterialTipo.rotulo)).all()
    subjects = session.scalars(select(Subject).where(Subject.encerrada_em.is_(None)).order_by(Subject.nome)).all()
    gdocs = [m for m in materials if m.origem == "gdoc"]
    return templates.TemplateResponse(
        request,
        "materials.html",
        {
            "materials": materials,
            "unlinked": unlinked,
            "tipos": tipos,
            "subjects": subjects,
            "gdocs": gdocs,
            "erro": request.query_params.get("erro"),
            "sync_resumo": request.query_params.get("sincronizado"),
        },
    )


@router.post("/sync")
def sync_now(session: Session = Depends(get_session)):
    """Botão "Sincronizar agora" (PLANO.md) — o mesmo caminho que um
    cron/systemd timer bateria a cada ~10 min; aqui é sob demanda."""
    if not config.GOOGLE_DRIVE_FOLDER_ID:
        erro = _url_escape("GOOGLE_DRIVE_FOLDER_ID não configurado")
        return RedirectResponse(url=f"/materials?erro={erro}", status_code=303)
    try:
        client = get_drive_client()
    except RuntimeError as exc:
        return RedirectResponse(url=f"/materials?erro={_url_escape(str(exc))}", status_code=303)

    resumo = sync_drive_folder(session, client, config.GOOGLE_DRIVE_FOLDER_ID)
    return RedirectResponse(
        url=f"/materials?sincronizado={resumo['synced']}+de+{resumo['total']}", status_code=303
    )


@router.post("")
def create_material(
    titulo: str = Form(...),
    origem: str = Form(...),
    tipo_id: str = Form(""),
    url: str = Form(""),
    texto: str = Form(""),
    subject_id: str = Form(""),
    lesson_id: str = Form(""),
    arquivo: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    material = Material(
        titulo=titulo.strip(),
        origem=origem,
        tipo_id=int(tipo_id) if tipo_id else None,
        status="ok",
    )

    if origem == "link":
        material.url = url.strip() or None
    elif origem == "texto":
        material.conteudo_md = texto.strip() or None
    elif origem in ("pdf", "foto"):
        if arquivo is None or not arquivo.filename:
            raise HTTPException(status_code=400, detail="arquivo obrigatório para origem pdf/foto")
        config.MATERIAL_FILES_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(arquivo.filename).suffix
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        dest = config.MATERIAL_FILES_DIR / stored_name
        with dest.open("wb") as out:
            shutil.copyfileobj(arquivo.file, out)
        material.path = str(dest)
        material.mime = arquivo.content_type
    else:
        raise HTTPException(status_code=400, detail="origem inválida pra cadastro manual")

    session.add(material)
    session.flush()

    if subject_id:
        session.add(
            MaterialUse(
                material_id=material.id,
                subject_id=int(subject_id),
                lesson_id=int(lesson_id) if lesson_id else None,
            )
        )
    session.commit()
    return RedirectResponse(url="/materials", status_code=303)


@router.post("/{material_id}/vincular")
def link_material(
    material_id: int,
    subject_id: int = Form(...),
    lesson_id: str = Form(""),
    session: Session = Depends(get_session),
):
    """Resolve a caixa "Não vinculados" num clique (PLANO.md)."""
    material = _get_material_or_404(session, material_id)
    session.add(
        MaterialUse(
            material_id=material.id,
            subject_id=subject_id,
            lesson_id=int(lesson_id) if lesson_id else None,
        )
    )
    session.commit()
    return RedirectResponse(url="/materials", status_code=303)


@router.post("/{material_id}/tipo")
def set_tipo(material_id: int, tipo_id: str = Form(""), session: Session = Depends(get_session)):
    material = _get_material_or_404(session, material_id)
    material.tipo_id = int(tipo_id) if tipo_id else None
    session.commit()
    return RedirectResponse(url="/materials", status_code=303)


@router.post("/{material_id}/tags")
def add_tag(material_id: int, tag: str = Form(...), session: Session = Depends(get_session)):
    material = _get_material_or_404(session, material_id)
    normalized = tag.strip().lower()
    if normalized:
        exists = session.scalar(
            select(MaterialTag.id).where(MaterialTag.material_id == material_id, MaterialTag.tag == normalized)
        )
        if exists is None:
            session.add(MaterialTag(material_id=material_id, tag=normalized))
            session.commit()
    return RedirectResponse(url=f"/materials/{material_id}", status_code=303)


@router.post("/{material_id}/tags/{tag_id}/remover")
def remove_tag(material_id: int, tag_id: int, session: Session = Depends(get_session)):
    tag = session.get(MaterialTag, tag_id)
    if tag is not None and tag.material_id == material_id:
        session.delete(tag)
        session.commit()
    return RedirectResponse(url=f"/materials/{material_id}", status_code=303)


@router.get("/{material_id}")
def material_detail(request: Request, material_id: int, session: Session = Depends(get_session)):
    material = _get_material_or_404(session, material_id)
    tipos = session.scalars(select(MaterialTipo).order_by(MaterialTipo.rotulo)).all()
    subjects = session.scalars(select(Subject).where(Subject.encerrada_em.is_(None)).order_by(Subject.nome)).all()
    return templates.TemplateResponse(
        request, "material_detail.html", {"material": material, "tipos": tipos, "subjects": subjects}
    )


@router.get("/{material_id}/arquivo")
def material_file(material_id: int, session: Session = Depends(get_session)):
    material = _get_material_or_404(session, material_id)
    if not material.path:
        raise HTTPException(status_code=404, detail="material sem arquivo")
    path = Path(material.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="arquivo não encontrado no disco")
    return FileResponse(path, media_type=material.mime or "application/octet-stream")
