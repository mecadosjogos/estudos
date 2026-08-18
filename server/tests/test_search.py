from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _make_transcribed_lesson(session, texts, titulo="Aula com transcrição"):
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    transcript = Transcript(
        lesson_id=lesson.id,
        engine="faster-whisper-large-v3",
        worker_name="desktop-4070",
        full_text=" ".join(texts),
        duration_s=float(len(texts) * 10),
    )
    session.add(transcript)
    session.flush()

    for i, text in enumerate(texts):
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                idx=i,
                start_s=float(i * 10),
                end_s=float(i * 10 + 8),
                text=text,
                words_json="[]",
            )
        )
    session.commit()
    return lesson.id


def test_search_finds_matching_segment(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(
            session, ["o prazo da usucapião extraordinária é de quinze anos"]
        )

    response = client.get("/search", params={"q": "usucapião"})
    assert response.status_code == 200
    assert "Aula com transcrição" in response.text
    assert "<mark>" in response.text


def test_search_is_accent_insensitive(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, ["a usucapião extraordinária independe de justo título"])

    response = client.get("/search", params={"q": "usucapiao"})
    assert response.status_code == 200
    assert "Aula com transcrição" in response.text


def test_search_no_results(app_env):
    client = _authed_client()
    response = client.get("/search", params={"q": "termo-que-nao-existe-em-lugar-nenhum"})
    assert response.status_code == 200
    assert "Nada encontrado" in response.text


def test_search_link_points_to_the_right_timestamp(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(
            session, ["fato irrelevante", "aqui fala de negócio jurídico direto"]
        )

    response = client.get("/search", params={"q": "negócio"})
    assert f"/lessons/{lesson_id}/transcricao?t=10.0" in response.text


def test_search_tolerates_special_characters(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, ["o art. 1.238 do código civil trata da usucapião"])

    for query in ["art. 1.238", "usucapião-extraordinária", 'aspas"soltas', "* -- OR"]:
        response = client.get("/search", params={"q": query})
        assert response.status_code == 200, f"query {query!r} quebrou a busca"


def test_reprocessing_removes_old_segments_from_search_index(app_env):
    """Reindexar é apagar-e-regravar (Integridade #2 do PLANO.md) — a busca
    não pode continuar achando um texto que já foi substituído."""
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Transcript

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["conteúdo antigo e específico da primeira versão"])

    before = client.get("/search", params={"q": "específico"})
    assert "Aula com transcrição" in before.text

    with holder.SessionLocal() as session:
        old = session.scalar(select(Transcript).where(Transcript.lesson_id == lesson_id))
        session.delete(old)
        session.commit()

    after = client.get("/search", params={"q": "específico"})
    assert "Nada encontrado" in after.text


def test_lesson_transcript_page_renders_synced_segments(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["primeiro trecho", "segundo trecho"])

    response = client.get(f"/lessons/{lesson_id}/transcricao")
    assert response.status_code == 200
    assert 'data-start="0.0"' in response.text
    assert 'data-start="10.0"' in response.text
    assert "initReadingPage" in response.text


def test_lesson_audio_route_404_without_file(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["trecho qualquer"])

    response = client.get(f"/lessons/{lesson_id}/audio")
    assert response.status_code == 404


def test_lesson_audio_route_serves_file(app_env):
    from app import config

    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["trecho qualquer"])

    config.MEDIA_WEB_DIR.mkdir(parents=True, exist_ok=True)
    (config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3").write_bytes(b"fake-mp3-bytes")

    response = client.get(f"/lessons/{lesson_id}/audio")
    assert response.status_code == 200
    assert response.content == b"fake-mp3-bytes"


def test_save_position_persists(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["trecho"])

    response = client.post(f"/lessons/{lesson_id}/posicao", json={"posicao_s": 123.5})
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        assert session.get(Lesson, lesson_id).posicao_s == 123.5
