"""Biblioteca (PLANO.md, fase 10): obra permanente e sem matéria, cada
porção subida vira um `Material` ligado a ela, cada página de um
`MaterialPage`. Quem carrega matéria/semestre é o uso (`MaterialUse`,
fase 9) -- mesmo princípio de Assunto/AssuntoCobertura.
"""

import html
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_session
from ..db import get_session
from ..glossary.index import load_active_variants
from ..glossary.render import highlight_html
from ..library import pdf as pdf_lib
from ..library.abnt import build_citation_with_page, build_reference
from ..library.coverage import section_coverage
from ..library.ingest import find_overlapping_materials, ingest_pdf, ingest_photos, save_uploaded_files
from ..models import Material, MaterialPage, MaterialUse, Subject, Work, WorkImage, WorkSection

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:300])


def _content_disposition(filename: str) -> str:
    """Título de obra pode ter acento -- e um header HTTP não aceita
    bytes fora de ASCII na forma `filename="..."` (é exatamente o mesmo
    tipo de armadilha de encoding do curl documentada no RUNBOOK.md, só
    que aqui do lado do servidor). Mesma lógica que `FileResponse` do
    Starlette usa: quando o nome tem caractere não-ASCII, manda só a
    forma `filename*=utf-8''<percent-encoded>` (RFC 6266)."""
    from urllib.parse import quote

    encoded = quote(filename)
    if encoded != filename:
        return f"attachment; filename*=utf-8''{encoded}"
    return f'attachment; filename="{filename}"'


def _get_work_or_404(session: Session, work_id: int) -> Work:
    work = session.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="obra não encontrada")
    return work


@router.get("/works")
def list_works(request: Request, session: Session = Depends(get_session)):
    works = session.scalars(select(Work).order_by(Work.titulo)).all()
    return templates.TemplateResponse(request, "works.html", {"works": works})


@router.post("/works")
def create_work(
    titulo: str = Form(...),
    subtitulo: str = Form(""),
    autores: str = Form(""),
    organizadores: str = Form(""),
    tradutor: str = Form(""),
    edicao: str = Form(""),
    volume: str = Form(""),
    tomo: str = Form(""),
    local: str = Form(""),
    editora: str = Form(""),
    ano: str = Form(""),
    isbn: str = Form(""),
    session: Session = Depends(get_session),
):
    work = Work(
        titulo=titulo.strip(),
        subtitulo=subtitulo.strip() or None,
        autores=autores.strip() or None,
        organizadores=organizadores.strip() or None,
        tradutor=tradutor.strip() or None,
        edicao=edicao.strip() or None,
        volume=volume.strip() or None,
        tomo=tomo.strip() or None,
        local=local.strip() or None,
        editora=editora.strip() or None,
        ano=int(ano) if ano.strip() else None,
        isbn=isbn.strip() or None,
    )
    session.add(work)
    session.commit()
    return RedirectResponse(url=f"/works/{work.id}", status_code=303)


@router.get("/works/{work_id}")
def work_detail(request: Request, work_id: int, session: Session = Depends(get_session)):
    work = _get_work_or_404(session, work_id)
    materials = session.scalars(
        select(Material).where(Material.work_id == work_id).order_by(Material.pagina_inicial, Material.ordem_manual)
    ).all()
    subjects = session.scalars(select(Subject).where(Subject.encerrada_em.is_(None)).order_by(Subject.nome)).all()
    uses = session.scalars(
        select(MaterialUse).join(Material, MaterialUse.material_id == Material.id).where(Material.work_id == work_id)
    ).all()
    cobertura = section_coverage(work.sections, materials)
    return templates.TemplateResponse(
        request,
        "work_detail.html",
        {
            "work": work,
            "materials": materials,
            "subjects": subjects,
            "uses": uses,
            "cobertura": cobertura,
            "referencia": build_reference(work),
            "erro": request.query_params.get("erro"),
        },
    )


@router.post("/works/{work_id}")
def update_work(
    work_id: int,
    titulo: str = Form(...),
    subtitulo: str = Form(""),
    autores: str = Form(""),
    organizadores: str = Form(""),
    tradutor: str = Form(""),
    edicao: str = Form(""),
    volume: str = Form(""),
    tomo: str = Form(""),
    local: str = Form(""),
    editora: str = Form(""),
    ano: str = Form(""),
    isbn: str = Form(""),
    referencia_manual: str = Form(""),
    session: Session = Depends(get_session),
):
    work = _get_work_or_404(session, work_id)
    work.titulo = titulo.strip()
    work.subtitulo = subtitulo.strip() or None
    work.autores = autores.strip() or None
    work.organizadores = organizadores.strip() or None
    work.tradutor = tradutor.strip() or None
    work.edicao = edicao.strip() or None
    work.volume = volume.strip() or None
    work.tomo = tomo.strip() or None
    work.local = local.strip() or None
    work.editora = editora.strip() or None
    work.ano = int(ano) if ano.strip() else None
    work.isbn = isbn.strip() or None
    work.referencia_manual = referencia_manual.strip() or None
    session.commit()
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.post("/works/{work_id}/imagens")
def upload_work_image(
    work_id: int,
    tipo: str = Form(...),
    arquivo: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    work = _get_work_or_404(session, work_id)
    saved = save_uploaded_files([arquivo], dest_subdir="obras")
    session.add(WorkImage(work_id=work.id, tipo=tipo, path=saved[0]))
    session.commit()
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.get("/works/{work_id}/imagens/{image_id}")
def work_image_file(work_id: int, image_id: int, session: Session = Depends(get_session)):
    image = session.get(WorkImage, image_id)
    if image is None or image.work_id != work_id:
        raise HTTPException(status_code=404, detail="imagem não encontrada")
    path = Path(image.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="arquivo não encontrado no disco")
    return FileResponse(path)


@router.post("/works/{work_id}/sections")
def add_work_section(
    work_id: int,
    titulo: str = Form(...),
    nivel: str = Form("1"),
    pagina_inicial: int = Form(...),
    pagina_final: str = Form(""),
    session: Session = Depends(get_session),
):
    work = _get_work_or_404(session, work_id)
    ordem = (session.scalar(select(WorkSection.ordem).where(WorkSection.work_id == work_id).order_by(WorkSection.ordem.desc())) or 0) + 1
    session.add(
        WorkSection(
            work_id=work.id,
            ordem=ordem,
            nivel=int(nivel) if nivel.strip() else 1,
            titulo=titulo.strip(),
            pagina_inicial=pagina_inicial,
            pagina_final=int(pagina_final) if pagina_final.strip() else None,
        )
    )
    session.commit()
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.post("/works/{work_id}/sections/{section_id}/remover")
def remove_work_section(work_id: int, section_id: int, session: Session = Depends(get_session)):
    section = session.get(WorkSection, section_id)
    if section is not None and section.work_id == work_id:
        session.delete(section)
        session.commit()
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.post("/works/{work_id}/materiais")
def upload_work_material(
    work_id: int,
    titulo: str = Form(...),
    origem: str = Form(...),
    pagina_inicial: str = Form(""),
    pagina_final: str = Form(""),
    ordem_manual_confirmado: str = Form(""),
    sobrepor_confirmado: str = Form(""),
    arquivo: UploadFile | None = File(None),
    arquivos: list[UploadFile] | None = File(None),
    session: Session = Depends(get_session),
):
    """Sobe uma porção da obra: um PDF (extração nativa + páginas
    escaneadas renderizadas) ou várias fotos em ordem. `pagina_inicial`/
    `pagina_final` são o intervalo real na obra -- sem eles, cai em
    `ordem_manual` (numeração desconhecida), e o front pede confirmação
    explícita disso via `ordem_manual_confirmado` antes de aceitar."""
    work = _get_work_or_404(session, work_id)

    pi = int(pagina_inicial) if pagina_inicial.strip() else None
    pf = int(pagina_final) if pagina_final.strip() else None

    if pi is None and not ordem_manual_confirmado:
        erro = _url_escape("Página inicial não informada -- confirme que a numeração é mesmo desconhecida")
        return RedirectResponse(url=f"/works/{work_id}?erro={erro}", status_code=303)

    if pi is not None and pf is not None and not sobrepor_confirmado:
        conflitos = find_overlapping_materials(session, work_id, pi, pf)
        if conflitos:
            titulos = ", ".join(c.titulo for c in conflitos)
            erro = _url_escape(
                f"Intervalo p. {pi}-{pf} sobrepõe material já existente ({titulos}). "
                "Marque \"sobrepor mesmo assim\" se for intencional (ex.: foto melhor)."
            )
            return RedirectResponse(url=f"/works/{work_id}?erro={erro}", status_code=303)

    material = Material(
        titulo=titulo.strip(),
        origem=origem,
        work_id=work.id,
        pagina_inicial=pi,
        pagina_final=pf,
        status="ok",
    )
    if pi is None:
        next_manual = (
            session.scalar(
                select(Material.ordem_manual)
                .where(Material.work_id == work_id, Material.ordem_manual.is_not(None))
                .order_by(Material.ordem_manual.desc())
            )
            or 0
        ) + 1
        material.ordem_manual = next_manual

    session.add(material)
    session.flush()

    if origem == "pdf":
        if arquivo is None or not arquivo.filename:
            raise HTTPException(status_code=400, detail="arquivo PDF obrigatório")
        saved = save_uploaded_files([arquivo], dest_subdir="obras")
        material.path = saved[0]
        material.mime = "application/pdf"
        ingest_pdf(session, material)
    elif origem == "foto":
        fotos = [f for f in (arquivos or []) if f.filename]
        if not fotos:
            raise HTTPException(status_code=400, detail="pelo menos uma foto obrigatória")
        saved = save_uploaded_files(fotos, dest_subdir="obras")
        ingest_photos(session, material, saved)
    else:
        raise HTTPException(status_code=400, detail="origem inválida -- use pdf ou foto")

    session.commit()
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.post("/works/{work_id}/usos")
def add_work_use(
    work_id: int,
    material_id: int = Form(...),
    subject_id: int = Form(...),
    pagina_inicial: str = Form(""),
    pagina_final: str = Form(""),
    rotulo: str = Form(""),
    session: Session = Depends(get_session),
):
    """Marcar trecho por matéria (PLANO.md) -- o mesmo material acumula
    quantos usos você quiser, cada um com seu recorte de páginas. Não
    precisa acontecer no upload: pode ser adicionado a qualquer momento
    futuro, sem reprocessar nada."""
    material = session.get(Material, material_id)
    if material is None or material.work_id != work_id:
        raise HTTPException(status_code=404, detail="material não encontrado nesta obra")
    session.add(
        MaterialUse(
            material_id=material_id,
            subject_id=subject_id,
            pagina_inicial=int(pagina_inicial) if pagina_inicial.strip() else None,
            pagina_final=int(pagina_final) if pagina_final.strip() else None,
            rotulo=rotulo.strip() or None,
        )
    )
    session.commit()
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.get("/works/{work_id}/ler")
def read_work(request: Request, work_id: int, session: Session = Depends(get_session)):
    """A leitura do material (PLANO.md): capítulo corrido, marcador de
    página, ▸ ver a página original. Só páginas "ok" aparecem no texto
    corrido; pendentes/erro aparecem sinalizadas, sem quebrar a leitura."""
    work = _get_work_or_404(session, work_id)
    pages = session.scalars(
        select(MaterialPage)
        .join(Material, MaterialPage.material_id == Material.id)
        .where(Material.work_id == work_id)
        .order_by(Material.pagina_inicial, Material.ordem_manual, MaterialPage.ordem)
    ).all()
    # Glossário (fase 11): mesma marcação em tempo de renderização da aula
    # editada -- "em todo texto do app... capítulo de livro" (PLANO.md).
    variants = load_active_variants(session)
    glossary_html = {
        page.id: highlight_html(html.escape(page.texto), variants) for page in pages if page.texto
    }
    return templates.TemplateResponse(
        request, "work_read.html", {"work": work, "pages": pages, "glossary_html": glossary_html}
    )


@router.get("/materials/{material_id}/paginas/{page_id}/imagem")
def material_page_image(material_id: int, page_id: int, session: Session = Depends(get_session)):
    page = session.get(MaterialPage, page_id)
    if page is None or page.material_id != material_id:
        raise HTTPException(status_code=404, detail="página não encontrada")
    path = Path(page.image_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="imagem não encontrada no disco")
    return FileResponse(path)


@router.post("/materials/{material_id}/paginas/{page_id}/editar")
def edit_material_page(
    material_id: int,
    page_id: int,
    texto: str = Form(...),
    session: Session = Depends(get_session),
):
    """Correção manual sua, pelo formulário da tela de leitura --
    `editado_em` protege o texto: `colar` (abaixo) recusa sobrescrever
    depois disso."""
    from datetime import datetime, timezone

    page = session.get(MaterialPage, page_id)
    if page is None or page.material_id != material_id:
        raise HTTPException(status_code=404, detail="página não encontrada")
    page.texto = texto
    page.status = "ok"
    page.editado_em = datetime.now(timezone.utc)
    session.commit()
    work_id = page.material.work_id
    return RedirectResponse(url=f"/works/{work_id}/ler#pagina-{page.id}", status_code=303)


@router.post("/materials/{material_id}/paginas/{page_id}/colar")
def paste_material_page_transcription(
    material_id: int,
    page_id: int,
    texto: str = Form(...),
    session: Session = Depends(get_session),
):
    """Ponte manual da transcrição por visão (RUNBOOK.md, "Transcrever
    páginas"): o Claude Code lê a foto (baixada via
    GET .../imagem) e cola o resultado aqui. Nunca sobrescreve uma página
    que você já corrigiu à mão (`editado_em`) -- "refazer" numa página
    protegida para com um erro em vez de apagar sua correção em
    silêncio."""
    page = session.get(MaterialPage, page_id)
    if page is None or page.material_id != material_id:
        raise HTTPException(status_code=404, detail="página não encontrada")
    if page.editado_em is not None:
        raise HTTPException(
            status_code=409, detail="página já foi corrigida manualmente -- não sobrescrevo. Edite direto se for para mudar."
        )

    from ..models import AiCall

    ai_call = AiCall(lesson_id=None, tipo_acao="transcrever_pagina", via="manual", modelo="manual", custo_usd=0.0)
    session.add(ai_call)
    session.flush()

    page.texto = texto
    page.status = "ok"
    page.extraido_por = "visao"
    page.erro = None
    page.ai_call_id = ai_call.id
    session.commit()
    return {"ok": True, "material_id": material_id, "page_id": page_id, "status": page.status}


@router.post("/materials/{material_id}/paginas/{page_id}/erro")
def mark_material_page_error(
    material_id: int,
    page_id: int,
    erro: str = Form(...),
    session: Session = Depends(get_session),
):
    """Uma página que falhou (letra ilegível, foto ruim) fica marcada
    sozinha, sem travar o resto do material (PLANO.md: "uma página que
    falha fica marcada sozinha, sem travar o resto")."""
    page = session.get(MaterialPage, page_id)
    if page is None or page.material_id != material_id:
        raise HTTPException(status_code=404, detail="página não encontrada")
    page.status = "erro"
    page.erro = erro.strip()[:500]
    session.commit()
    return {"ok": True, "material_id": material_id, "page_id": page_id, "status": page.status}


@router.get("/works/{work_id}/citar")
def cite_work(work_id: int, pagina: str = "", session: Session = Depends(get_session)):
    work = _get_work_or_404(session, work_id)
    pagina_int = int(pagina) if pagina.strip() else None
    return PlainTextResponse(build_citation_with_page(work, pagina_int))


@router.get("/works/{work_id}/baixar")
def download_work(
    work_id: int,
    formato: str = "md",
    pagina_inicial: str = "",
    pagina_final: str = "",
    session: Session = Depends(get_session),
):
    """Baixar (PLANO.md): .md ou .txt, com referência ABNT e intervalo de
    páginas no cabeçalho -- o arquivo já sabe de onde veio."""
    work = _get_work_or_404(session, work_id)
    pi = int(pagina_inicial) if pagina_inicial.strip() else None
    pf = int(pagina_final) if pagina_final.strip() else None

    query = (
        select(MaterialPage)
        .join(Material, MaterialPage.material_id == Material.id)
        .where(Material.work_id == work_id, MaterialPage.status == "ok")
        .order_by(Material.pagina_inicial, Material.ordem_manual, MaterialPage.ordem)
    )
    pages = session.scalars(query).all()
    if pi is not None:
        pages = [p for p in pages if p.pagina_obra is not None and p.pagina_obra >= pi]
    if pf is not None:
        pages = [p for p in pages if p.pagina_obra is not None and p.pagina_obra <= pf]

    referencia = build_reference(work)
    intervalo = f"p. {pi}-{pf}" if pi is not None and pf is not None else "obra inteira"
    cabecalho = f"{referencia}\n({intervalo})\n\n---\n\n"

    corpo_partes = []
    for page in pages:
        marcador = f"— p. {page.pagina_obra} —" if page.pagina_obra is not None else "— página s/n —"
        corpo_partes.append(f"{marcador}\n\n{page.texto or ''}")
    corpo = "\n\n".join(corpo_partes)

    content = cabecalho + corpo
    ext = "md" if formato == "md" else "txt"
    filename = f"{work.titulo[:40]}.{ext}"
    return PlainTextResponse(
        content,
        media_type="text/markdown" if formato == "md" else "text/plain",
        headers={"Content-Disposition": _content_disposition(filename)},
    )
