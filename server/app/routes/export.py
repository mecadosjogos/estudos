"""Exportar e imprimir (PLANO.md, fase 14): aula editada em PDF,
bibliografia ABNT da matéria, e o corpus inteiro em .zip de Markdown --
"protege contra você querer sair do app"."""

import html as html_lib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..export.bibliografia import build_bibliografia_txt
from ..export.corpus import build_corpus_zip
from ..export.lesson_export import build_edited_lesson_html
from ..export.pdf import render_html_to_pdf
from ..glossary.index import load_active_variants
from ..glossary.render import highlight_html
from ..models import EditedBlock, Lesson, Subject

router = APIRouter(dependencies=[Depends(require_session)])


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
