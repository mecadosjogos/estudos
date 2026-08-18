"""Busca simples sobre a transcrição (PLANO.md, fase 5).

FTS5 com `remove_diacritics 2`: buscar "usucapiao" sem acento acha
"usucapião". Cada termo do usuário entra entre aspas na query FTS pra
evitar que caracteres como `-`, `:`, `*` quebrem a sintaxe do MATCH — sem
isso, uma busca com hífen ou apóstrofo vira erro 500 em vez de resultado.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _build_fts_query(q: str) -> str:
    terms = q.strip().split()
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms if t]
    return " ".join(quoted)


@router.get("/search")
def search(request: Request, q: str = "", session: Session = Depends(get_session)):
    results = []
    if q.strip():
        fts_query = _build_fts_query(q)
        rows = session.execute(
            text(
                """
                SELECT
                    lesson.id AS lesson_id,
                    lesson.titulo AS lesson_titulo,
                    lesson.data AS lesson_data,
                    subject.sigla AS subject_sigla,
                    transcript_segment.start_s AS start_s,
                    snippet(transcript_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet
                FROM transcript_fts
                JOIN transcript_segment ON transcript_segment.id = transcript_fts.rowid
                JOIN transcript ON transcript.id = transcript_segment.transcript_id
                JOIN lesson ON lesson.id = transcript.lesson_id
                JOIN subject ON subject.id = lesson.subject_id
                WHERE transcript_fts MATCH :query
                ORDER BY bm25(transcript_fts)
                LIMIT 30
                """
            ),
            {"query": fts_query},
        ).mappings().all()
        results = list(rows)

    return templates.TemplateResponse(request, "search.html", {"q": q, "results": results})
