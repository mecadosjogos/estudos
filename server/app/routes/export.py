"""Exportar e imprimir (PLANO.md, fase 14): aula editada em PDF,
bibliografia ABNT da matéria, e o corpus inteiro em .zip de Markdown --
"protege contra você querer sair do app"."""

import html as html_lib

import markdown as markdown_lib
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..export.bibliografia import build_bibliografia_txt
from ..export.corpus import build_corpus_zip
from ..export.lesson_export import build_edited_lesson_html
from ..export.pdf import add_header_footer, render_html_to_pdf
from ..glossary.index import load_active_variants
from ..glossary.mermaid import build_taxonomy_tree
from ..glossary.render import highlight_html
from ..models import EditedBlock, Lesson, Subject

router = APIRouter(dependencies=[Depends(require_session)])

# Identificação impressa em todo PDF exportado (app de uso pessoal, não
# multiusuário -- texto fixo, mesmo espírito de admin/admin e das 5
# matérias fixas do semestre). Segunda linha é a matéria da aula, uma por
# PDF -- variável, por isso não entra na constante.
_CABECALHO_LINHA1 = "Wyver Godoi - Direito - Semestre 1/10"


@router.get("/lessons/{lesson_id}/aula-editada.pdf")
def download_edited_lesson_pdf(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    blocks = session.scalars(
        select(EditedBlock)
        .where(EditedBlock.lesson_id == lesson_id, EditedBlock.orfao_em.is_(None))
        .order_by(EditedBlock.ordem)
    ).all()
    variants = load_active_variants(session)
    glossary_html = {
        block.id: highlight_html(html_lib.escape(block.texto), variants) for block in blocks
    }
    html = build_edited_lesson_html(lesson, blocks, glossary_html)
    pdf_bytes = render_html_to_pdf(html)
    filename = f"aula-editada-{lesson_id}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _taxonomy_html(nodes: list[dict]) -> str:
    """Mapa de taxonomia (doutrina geral, `mapa_mermaid`) como lista
    aninhada em HTML -- não dá pra reproduzir o diagrama Mermaid de
    verdade no PDF (`fitz.Story` não roda JS), então reaproveita
    `build_taxonomy_tree` (já usado pela "Taxonomia da matéria") e
    desenha só a estrutura como texto, igual à árvore de conhecimento do
    guia."""
    if not nodes:
        return ""
    items = "".join(f"<li>{html_lib.escape(n['label'])}{_taxonomy_html(n['children'])}</li>" for n in nodes)
    return f"<ul>{items}</ul>"


@router.get("/lessons/{lesson_id}/guia.pdf")
def download_guia_pdf(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")

    partes = []
    if lesson.mapa_mermaid:
        arvore = build_taxonomy_tree(session, [lesson.mapa_mermaid])
        partes.append(f"<h2>Mapa de taxonomia (doutrina geral)</h2>{_taxonomy_html(arvore)}<hr>")
    partes.append(markdown_lib.markdown(lesson.guia_md, extensions=["extra"]))

    pdf_bytes = render_html_to_pdf("".join(partes))
    pdf_bytes = add_header_footer(pdf_bytes, f"{_CABECALHO_LINHA1}\n{lesson.subject.nome}")
    filename = f"guia-aula-{lesson_id}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/subjects/{subject_id}/bibliografia.txt")
def download_bibliografia(subject_id: int, session: Session = Depends(get_session)):
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="matéria não encontrada")
    content = build_bibliografia_txt(session, subject_id)
    filename = f"bibliografia-{subject.sigla}.txt"
    return PlainTextResponse(
        content, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/export/corpus.zip")
def download_corpus(session: Session = Depends(get_session)):
    data = build_corpus_zip(session)
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="corpus.zip"'},
    )
