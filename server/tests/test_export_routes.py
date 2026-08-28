import io
import json
import zipfile
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _subject_id(session, sigla="TGDC"):
    from sqlalchemy import select

    from app.models import Subject

    return session.scalar(select(Subject.id).where(Subject.sigla == sigla))


def _lesson_with_transcript_id(session, titulo="Aula export") -> int:
    from app.models import Lesson, Transcript, TranscriptSegment

    subject_id = _subject_id(session)
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()
    transcript = Transcript(
        lesson_id=lesson.id, engine="e", worker_name="w",
        full_text="a posse exige corpus e animus", duration_s=5.0,
    )
    session.add(transcript)
    session.flush()
    session.add(TranscriptSegment(
        transcript_id=transcript.id, idx=0, start_s=0.0, end_s=5.0,
        text="a posse exige corpus e animus", words_json="[]",
    ))
    session.commit()
    return lesson.id


def _pasted_response():
    payload = {
        "resumo": "Resumo de teste export.",
        "aula_editada": [
            {"tipo": "conceito", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [], "guia_titulo": "Posse",
        "guia_secoes": [{"titulo": "Posse", "corpo": "Guia de teste export."}],
        "guia_topicos": [{"titulo": "Posse"}],
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_download_edited_lesson_pdf(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    response = client.get(f"/lessons/{lesson_id}/aula-editada.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"


def test_download_edited_lesson_pdf_404_without_lesson(app_env):
    client = _authed_client()
    response = client.get("/lessons/999999/aula-editada.pdf")
    assert response.status_code == 404


def test_download_bibliografia_empty(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)

    response = client.get(f"/subjects/{subject_id}/bibliografia.txt")
    assert response.status_code == 200
    assert "Nenhuma obra vinculada" in response.text


def test_download_bibliografia_with_works(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Material, MaterialUse, Work

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        work = Work(titulo="Instituições de Direito Civil", autores="Caio Mário da Silva Pereira", ano=2020)
        session.add(work)
        session.flush()
        material = Material(titulo="Cap 1", origem="pdf", status="ok", work_id=work.id)
        session.add(material)
        session.flush()
        session.add(MaterialUse(material_id=material.id, subject_id=subject_id))
        session.commit()

    response = client.get(f"/subjects/{subject_id}/bibliografia.txt")
    assert response.status_code == 200
    assert "PEREIRA, Caio Mário da Silva." in response.text


def test_download_corpus_zip_contains_expected_files(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    response = client.get("/export/corpus.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()
    assert "glossario.md" in names
    assert "assuntos.md" in names
    assert "materiais.md" in names
    assert any(n.endswith("/transcricao.md") for n in names)
    assert any(n.endswith("/aula-editada.md") for n in names)
    assert any(n.endswith("/guia.md") for n in names)

    guia_name = next(n for n in names if n.endswith("/guia.md"))
    assert "Guia de teste export." in zf.read(guia_name).decode("utf-8")

    transcricao_name = next(n for n in names if n.endswith("/transcricao.md"))
    assert "posse exige corpus" in zf.read(transcricao_name).decode("utf-8")
