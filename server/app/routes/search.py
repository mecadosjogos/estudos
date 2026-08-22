"""Busca unificada (PLANO.md, fase 12): transcrição, materiais (Docs e
livros), observações e definições do glossário, cada fonte com seu
próprio índice FTS5 (mesmo padrão da transcrição, fase 5), combinadas
numa lista só por `bm25`. Um termo do glossário casado pelo texto (nome
ou variante) fica fixado no topo, fora da lista combinada.

`remove_diacritics 2` em todos os índices: buscar "usucapiao" sem acento
acha "usucapião" em qualquer fonte. Cada termo do usuário entra entre
aspas na query FTS pra evitar que caracteres como `-`, `:`, `*` quebrem a
sintaxe do MATCH.
"""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..glossary.normalize import normalize_char_preserving
from ..models import Definition, Subject, Term, TermAlias

router = APIRouter(dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

SOURCE_LABELS = {
    "transcricao": "Transcrição",
    "material": "Material",
    "pagina_obra": "Página de obra",
    "observacao": "Observação",
    "definicao": "Definição",
}

RESULTS_PER_SOURCE = 15
TOTAL_RESULTS = 40


def _build_fts_query(q: str) -> str:
    terms = q.strip().split()
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms if t]
    return " ".join(quoted)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _find_pinned_terms(session: Session, q: str) -> list[dict]:
    """"O termo casado fixado no topo... casando também pelas variantes"
    (PLANO.md) -- comparação exata pela grafia normalizada (sem acento,
    minúsculo), não substring: buscar "usucapião" não deve fixar todo
    termo que contém a palavra."""
    normalized_q = normalize_char_preserving(q.strip())
    if not normalized_q:
        return []

    matched_ids: set[int] = set()
    for term in session.scalars(select(Term)):
        if normalize_char_preserving(term.rotulo) == normalized_q:
            matched_ids.add(term.id)
    for alias in session.scalars(select(TermAlias)):
        if normalize_char_preserving(alias.alias) == normalized_q:
            matched_ids.add(alias.term_id)

    pinned = []
    for term_id in matched_ids:
        term = session.get(Term, term_id)
        definitions = session.scalars(
            select(Definition).where(Definition.term_id == term_id, Definition.status == "ativo")
        ).all()
        subjects = sorted({d.subject.sigla for d in definitions if d.subject is not None})
        pinned.append({"term": term, "count": len(definitions), "subjects": subjects})
    return pinned


def _transcript_results(session: Session, fts_query: str, subject_id: int | None, data_inicio, data_fim) -> list[dict]:
    conditions = ["transcript_fts MATCH :query"]
    params: dict = {"query": fts_query}
    if subject_id:
        conditions.append("lesson.subject_id = :subject_id")
        params["subject_id"] = subject_id
    if data_inicio:
        conditions.append("lesson.data >= :data_inicio")
        params["data_inicio"] = data_inicio.isoformat()
    if data_fim:
        conditions.append("lesson.data <= :data_fim")
        params["data_fim"] = data_fim.isoformat()
    where = " AND ".join(conditions)

    rows = session.execute(
        text(
            f"""
            SELECT
                lesson.id AS lesson_id,
                lesson.titulo AS titulo,
                lesson.data AS data,
                subject.sigla AS subject_sigla,
                transcript_segment.start_s AS start_s,
                snippet(transcript_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet,
                bm25(transcript_fts) AS score
            FROM transcript_fts
            JOIN transcript_segment ON transcript_segment.id = transcript_fts.rowid
            JOIN transcript ON transcript.id = transcript_segment.transcript_id
            JOIN lesson ON lesson.id = transcript.lesson_id
            JOIN subject ON subject.id = lesson.subject_id
            WHERE {where}
            ORDER BY bm25(transcript_fts)
            LIMIT :limit
            """
        ),
        {**params, "limit": RESULTS_PER_SOURCE},
    ).mappings().all()

    return [
        {
            "source_type": "transcricao",
            "subject_sigla": r["subject_sigla"],
            "titulo": r["titulo"],
            "data": r["data"],
            "snippet": r["snippet"],
            "url": f"/lessons/{r['lesson_id']}/transcricao?t={r['start_s']}",
            "score": r["score"],
        }
        for r in rows
    ]


def _material_results(session: Session, fts_query: str, subject_id: int | None, data_inicio, data_fim) -> list[dict]:
    # Sem filtro de período: um material solto (Doc, PDF avulso) não tem
    # uma data de origem confiável como uma aula -- simplificação
    # deliberada (ver PLANO.md, status desta fase).
    conditions = ["material_fts MATCH :query"]
    params: dict = {"query": fts_query}
    if subject_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM material_use WHERE material_use.material_id = material.id "
            "AND material_use.subject_id = :subject_id)"
        )
        params["subject_id"] = subject_id
    where = " AND ".join(conditions)

    rows = session.execute(
        text(
            f"""
            SELECT
                material.id AS material_id,
                material.titulo AS titulo,
                (
                    SELECT subject.sigla FROM material_use
                    JOIN subject ON subject.id = material_use.subject_id
                    WHERE material_use.material_id = material.id
                    ORDER BY material_use.criado_em LIMIT 1
                ) AS subject_sigla,
                snippet(material_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet,
                bm25(material_fts) AS score
            FROM material_fts
            JOIN material ON material.id = material_fts.rowid
            WHERE {where}
            ORDER BY bm25(material_fts)
            LIMIT :limit
            """
        ),
        {**params, "limit": RESULTS_PER_SOURCE},
    ).mappings().all()

    return [
        {
            "source_type": "material",
            "subject_sigla": r["subject_sigla"],
            "titulo": r["titulo"],
            "data": None,
            "snippet": r["snippet"],
            "url": f"/materials/{r['material_id']}",
            "score": r["score"],
        }
        for r in rows
    ]


def _material_page_results(session: Session, fts_query: str, subject_id: int | None, data_inicio, data_fim) -> list[dict]:
    # Mesma simplificação de material: página de obra não tem data de
    # origem, só filtro por matéria.
    conditions = ["material_page_fts MATCH :query"]
    params: dict = {"query": fts_query}
    if subject_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM material_use WHERE material_use.material_id = material.id "
            "AND material_use.subject_id = :subject_id)"
        )
        params["subject_id"] = subject_id
    where = " AND ".join(conditions)

    rows = session.execute(
        text(
            f"""
            SELECT
                material_page.id AS page_id,
                work.id AS work_id,
                work.titulo AS titulo,
                material_page.pagina_obra AS pagina_obra,
                (
                    SELECT subject.sigla FROM material_use
                    JOIN subject ON subject.id = material_use.subject_id
                    WHERE material_use.material_id = material.id
                    ORDER BY material_use.criado_em LIMIT 1
                ) AS subject_sigla,
                snippet(material_page_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet,
                bm25(material_page_fts) AS score
            FROM material_page_fts
            JOIN material_page ON material_page.id = material_page_fts.rowid
            JOIN material ON material.id = material_page.material_id
            JOIN work ON work.id = material.work_id
            WHERE {where}
            ORDER BY bm25(material_page_fts)
            LIMIT :limit
            """
        ),
        {**params, "limit": RESULTS_PER_SOURCE},
    ).mappings().all()

    return [
        {
            "source_type": "pagina_obra",
            "subject_sigla": r["subject_sigla"],
            "titulo": r["titulo"] + (f" — p. {r['pagina_obra']}" if r["pagina_obra"] is not None else ""),
            "data": None,
            "snippet": r["snippet"],
            "url": f"/works/{r['work_id']}/ler#pagina-{r['page_id']}",
            "cite_url": f"/works/{r['work_id']}/citar?pagina={r['pagina_obra']}" if r["pagina_obra"] is not None else None,
            "score": r["score"],
        }
        for r in rows
    ]


def _observacao_results(session: Session, fts_query: str, subject_id: int | None, data_inicio, data_fim) -> list[dict]:
    conditions = ["edited_block_observacao_fts MATCH :query"]
    params: dict = {"query": fts_query}
    if subject_id:
        conditions.append("lesson.subject_id = :subject_id")
        params["subject_id"] = subject_id
    if data_inicio:
        conditions.append("lesson.data >= :data_inicio")
        params["data_inicio"] = data_inicio.isoformat()
    if data_fim:
        conditions.append("lesson.data <= :data_fim")
        params["data_fim"] = data_fim.isoformat()
    where = " AND ".join(conditions)

    rows = session.execute(
        text(
            f"""
            SELECT
                lesson.id AS lesson_id,
                edited_block.id AS block_id,
                lesson.titulo AS titulo,
                lesson.data AS data,
                subject.sigla AS subject_sigla,
                snippet(edited_block_observacao_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet,
                bm25(edited_block_observacao_fts) AS score
            FROM edited_block_observacao_fts
            JOIN edited_block ON edited_block.id = edited_block_observacao_fts.rowid
            JOIN lesson ON lesson.id = edited_block.lesson_id
            JOIN subject ON subject.id = lesson.subject_id
            WHERE {where}
            ORDER BY bm25(edited_block_observacao_fts)
            LIMIT :limit
            """
        ),
        {**params, "limit": RESULTS_PER_SOURCE},
    ).mappings().all()

    return [
        {
            "source_type": "observacao",
            "subject_sigla": r["subject_sigla"],
            "titulo": r["titulo"],
            "data": r["data"],
            "snippet": r["snippet"],
            "url": f"/lessons/{r['lesson_id']}/aula-editada#bloco-{r['block_id']}",
            "score": r["score"],
        }
        for r in rows
    ]


def _definicao_results(session: Session, fts_query: str, subject_id: int | None, data_inicio, data_fim) -> list[dict]:
    conditions = ["definition_fts MATCH :query", "definition.status = 'ativo'", "definition.term_id IS NOT NULL"]
    params: dict = {"query": fts_query}
    if subject_id:
        conditions.append("definition.subject_id = :subject_id")
        params["subject_id"] = subject_id
    if data_inicio:
        conditions.append("(lesson.data IS NULL OR lesson.data >= :data_inicio)")
        params["data_inicio"] = data_inicio.isoformat()
    if data_fim:
        conditions.append("(lesson.data IS NULL OR lesson.data <= :data_fim)")
        params["data_fim"] = data_fim.isoformat()
    where = " AND ".join(conditions)

    rows = session.execute(
        text(
            f"""
            SELECT
                term.id AS term_id,
                term.rotulo AS titulo,
                lesson.data AS data,
                subject.sigla AS subject_sigla,
                snippet(definition_fts, 0, '<mark>', '</mark>', '…', 12) AS snippet,
                bm25(definition_fts) AS score
            FROM definition_fts
            JOIN definition ON definition.id = definition_fts.rowid
            JOIN term ON term.id = definition.term_id
            LEFT JOIN lesson ON lesson.id = definition.lesson_id
            LEFT JOIN subject ON subject.id = definition.subject_id
            WHERE {where}
            ORDER BY bm25(definition_fts)
            LIMIT :limit
            """
        ),
        {**params, "limit": RESULTS_PER_SOURCE},
    ).mappings().all()

    return [
        {
            "source_type": "definicao",
            "subject_sigla": r["subject_sigla"],
            "titulo": r["titulo"],
            "data": r["data"],
            "snippet": r["snippet"],
            "url": f"/termos/{r['term_id']}",
            "score": r["score"],
        }
        for r in rows
    ]


_SOURCE_FUNCS = {
    "transcricao": _transcript_results,
    "material": _material_results,
    "pagina_obra": _material_page_results,
    "observacao": _observacao_results,
    "definicao": _definicao_results,
}


@router.get("/search")
def search(
    request: Request,
    q: str = "",
    tipo: list[str] = Query(default=[]),
    subject_id: str = "",
    data_inicio: str = "",
    data_fim: str = "",
    session: Session = Depends(get_session),
):
    results: list[dict] = []
    pinned_terms: list[dict] = []

    subject_id_int = int(subject_id) if subject_id.strip().isdigit() else None
    data_inicio_parsed = _parse_date(data_inicio) if data_inicio.strip() else None
    data_fim_parsed = _parse_date(data_fim) if data_fim.strip() else None
    tipos_ativos = [t for t in tipo if t in SOURCE_LABELS] if tipo else list(SOURCE_LABELS)

    if q.strip():
        fts_query = _build_fts_query(q)
        pinned_terms = _find_pinned_terms(session, q)
        for source_type in tipos_ativos:
            results.extend(
                _SOURCE_FUNCS[source_type](session, fts_query, subject_id_int, data_inicio_parsed, data_fim_parsed)
            )
        results.sort(key=lambda r: r["score"])
        results = results[:TOTAL_RESULTS]

    subjects = session.scalars(select(Subject).order_by(Subject.sigla)).all()

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "q": q,
            "results": results,
            "pinned_terms": pinned_terms,
            "subjects": subjects,
            "source_labels": SOURCE_LABELS,
            "tipos_ativos": tipos_ativos,
            "subject_id": subject_id,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
        },
    )
