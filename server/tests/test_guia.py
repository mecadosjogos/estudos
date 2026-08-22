import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _make_transcribed_lesson(session, texts, titulo="Aula com transcrição"):
    from sqlalchemy import select

    from app.models import AudioSegment, Lesson, Subject, Transcript

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    session.add(AudioSegment(
        lesson_id=lesson.id, ordem=1, original_filename="aula.m4a",
        storage_path="/tmp/x", size_bytes=10, status="complete",
    ))

    transcript = Transcript(
        lesson_id=lesson.id, engine="e", worker_name="w",
        full_text=" ".join(texts), duration_s=float(len(texts) * 10),
    )
    session.add(transcript)
    session.commit()
    return lesson.id


def _pasted_response(guia_md="# Aula sem título identificado\n\nConteúdo do guia.") -> str:
    """O guia sai da MESMA resposta que a aula editada (fase 6 revisada) --
    não existe mais um `colar-guia` separado. Ver ai/schemas.py, guia_md."""
    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 5.0}],
        "guia_md": guia_md,
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_colar_resposta_saves_guia_alongside_aula_editada(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    resposta = _pasted_response("# Aula sem título identificado\n\n> A posse exige **corpus** e **animus**.")
    response = client.post(
        f"/lessons/{lesson_id}/colar-resposta", data={"resposta": resposta}, follow_redirects=True
    )
    assert response.status_code == 200
    assert response.url.path == f"/lessons/{lesson_id}/aula-editada"

    with holder.SessionLocal() as session:
        from app.models import Lesson

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_md.startswith("# Aula sem título identificado")
        assert lesson.guia_gerado_em is not None
        assert lesson.resumo == "Resumo curto."  # aula editada veio junto, mesma chamada


def test_view_guia_renders_markdown(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    resposta = _pasted_response("# Aula sem título identificado\n\n> A posse exige **corpus** e **animus**.")
    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": resposta})

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert response.status_code == 200
    assert "<strong>corpus</strong>" in response.text
    assert "<blockquote>" in response.text


def test_view_guia_404_before_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert response.status_code == 404


def test_download_guia_md_returns_raw_markdown(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response("# Guia\n\nconteúdo real")})

    response = client.get(f"/lessons/{lesson_id}/guia.md")
    assert response.status_code == 200
    assert response.text.strip() == "# Guia\n\nconteúdo real"
    assert "Content-Disposition" in response.headers


def test_lesson_detail_shows_view_guia_button_after_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response("# Guia\n\nconteúdo")})

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/guia\"" in response.text


def test_lesson_detail_hides_guia_button_before_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/guia\"" not in response.text


def test_guia_pacote_and_colar_guia_routes_no_longer_exist(app_env):
    """Rotas removidas na fase 6 revisada -- guia sai do mesmo
    pacote.md/colar-resposta da aula editada (ver ai/schemas.py, guia_md)."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    assert client.get(f"/lessons/{lesson_id}/guia-pacote.md").status_code == 404
    assert client.get(f"/lessons/{lesson_id}/colar-guia").status_code == 404
    assert client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": "# x"}).status_code == 404
