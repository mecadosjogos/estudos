"""Ingestão de material de biblioteca (PLANO.md, "Biblioteca"): fotos e PDF
entram pelo mesmo caminho — uma `MaterialPage` por página. PDF com camada de
texto extrai na hora (`extraido_por="nativo"`, sem custo, sem revisão
necessária); página sem texto (foto, ou PDF escaneado) fica `pendente`,
esperando a transcrição por leitura de imagem via Claude Code (ponte
manual — ver RUNBOOK.md, "Transcrever páginas").
"""

import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import Material, MaterialPage
from . import pdf as pdf_lib


def _pagina_obra(material: Material, ordem: int) -> int | None:
    """`ordem` é 0-indexado. Sem `pagina_inicial` conhecida (material usa
    `ordem_manual`), a numeração real da obra fica nula -- mostrada como
    "página desconhecida" em vez de inventar um número."""
    if material.pagina_inicial is None:
        return None
    return material.pagina_inicial + ordem


def ingest_photos(session: Session, material: Material, saved_paths: list[str]) -> None:
    """Uma `MaterialPage` por foto, na ordem em que os arquivos vieram --
    "várias fotos = um material, em ordem", mesmo padrão de "vários áudios
    = uma aula" (PLANO.md). Todas nascem `pendente`: foto sempre precisa
    de transcrição por leitura de imagem, nunca tem texto nativo."""
    for ordem, path in enumerate(saved_paths):
        session.add(
            MaterialPage(
                material_id=material.id,
                ordem=ordem,
                pagina_obra=_pagina_obra(material, ordem),
                image_path=path,
                status="pendente",
            )
        )


def ingest_pdf(session: Session, material: Material) -> None:
    """Uma `MaterialPage` por página do PDF. Página com camada de texto
    extrai na hora (`nativo`, `status="ok"`); sem texto (escaneada),
    renderiza como PNG e fica `pendente` -- mesmo caminho de uma foto a
    partir daqui."""
    assert material.path is not None
    contagem = pdf_lib.page_count(material.path)
    tem_texto = pdf_lib.has_native_text(material.path)

    pages_dir = config.MATERIAL_FILES_DIR / "paginas"
    pages_dir.mkdir(parents=True, exist_ok=True)

    for ordem in range(contagem):
        if tem_texto[ordem]:
            texto = pdf_lib.extract_native_text(material.path, ordem)
            session.add(
                MaterialPage(
                    material_id=material.id,
                    ordem=ordem,
                    pagina_obra=_pagina_obra(material, ordem),
                    image_path=material.path,  # a página original é o próprio PDF
                    texto=texto,
                    extraido_por="nativo",
                    status="ok",
                )
            )
        else:
            image_path = pages_dir / f"{uuid.uuid4().hex}.png"
            pdf_lib.render_page_as_image(material.path, ordem, str(image_path))
            session.add(
                MaterialPage(
                    material_id=material.id,
                    ordem=ordem,
                    pagina_obra=_pagina_obra(material, ordem),
                    image_path=str(image_path),
                    status="pendente",
                )
            )


def save_uploaded_files(files, dest_subdir: str = "") -> list[str]:
    """Salva uma lista de UploadFile em MATERIAL_FILES_DIR, devolvendo os
    caminhos na mesma ordem recebida -- a ordem em si é significativa
    (vira a ordem das páginas)."""
    dest_dir = config.MATERIAL_FILES_DIR / dest_subdir if dest_subdir else config.MATERIAL_FILES_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for upload in files:
        suffix = Path(upload.filename).suffix
        dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"
        with dest.open("wb") as out:
            shutil.copyfileobj(upload.file, out)
        saved.append(str(dest))
    return saved


def find_overlapping_materials(
    session: Session, work_id: int, pagina_inicial: int, pagina_final: int, exclude_material_id: int | None = None
) -> list[Material]:
    """Aviso de sobreposição (PLANO.md): um intervalo novo que invade um
    já existente da mesma obra. Só compara materiais com página conhecida
    -- os de `ordem_manual` não entram nessa checagem, porque não têm
    intervalo pra comparar."""
    query = select(Material).where(
        Material.work_id == work_id,
        Material.pagina_inicial.is_not(None),
        Material.pagina_final.is_not(None),
        Material.pagina_inicial <= pagina_final,
        Material.pagina_final >= pagina_inicial,
    )
    if exclude_material_id is not None:
        query = query.where(Material.id != exclude_material_id)
    return list(session.scalars(query))
