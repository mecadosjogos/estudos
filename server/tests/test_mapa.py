import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _lesson_with_transcript_id(session, titulo="Aula mapa") -> int:
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
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


def _pasted_response(mapa_mermaid):
    payload = {
        "resumo": "R.", "aula_editada": [
            {"tipo": "conceito", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0}
        ],
        "indice": [], "guia_md": "# G\n",
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": mapa_mermaid, "assuntos": [],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_processing_persists_mapa_mermaid(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    mermaid_src = "graph TD\n  A[Posse] --> B[Propriedade]"
    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(mermaid_src)})

    with holder.SessionLocal() as session:
        assert session.get(Lesson, lesson_id).mapa_mermaid == mermaid_src


def test_mapa_page_404_when_not_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.get(f"/lessons/{lesson_id}/mapa")
    assert response.status_code == 404


def test_mapa_page_renders_mermaid_source_and_links_glossary_node(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post("/termos/criar", data={"termo": "Posse", "definicao_md": "Def.", "citacao_literal": ""})

    mermaid_src = "graph TD\n  A[Posse] --> B[Propriedade]"
    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(mermaid_src)})

    response = client.get(f"/lessons/{lesson_id}/mapa")
    assert response.status_code == 200
    assert 'class="mermaid"' in response.text
    assert "A[Posse]" in response.text
    # o conteúdo de <pre> é escapado pelo Jinja2 (correto -- aspas viram
    # &#34;) e o navegador desfaz isso ao montar o DOM que o mermaid.js lê
    assert "click A &#34;/termos/" in response.text
    assert "mermaid.min.js" in response.text


def test_lesson_detail_shows_mapa_button_only_when_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/mapa" not in response.text

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response("graph TD\n  A[X]")})

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/mapa" in response.text
