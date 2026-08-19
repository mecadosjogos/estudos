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


def test_guia_pacote_contains_prompt_and_transcript(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    response = client.get(f"/lessons/{lesson_id}/guia-pacote.md")
    assert response.status_code == 200
    assert "FIDELIDADE AO CONTEÚDO" in response.text
    assert "ÁRVORE DE CONHECIMENTO" in response.text
    assert "a posse exige corpus e animus" in response.text


def test_guia_pacote_sem_transcricao_da_erro_400(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem transcrição", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    response = client.get(f"/lessons/{lesson_id}/guia-pacote.md")
    assert response.status_code == 400


def test_colar_guia_saves_markdown_and_redirects_to_view(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    resposta = "# Aula sem título identificado\n\n## Sumário\n\n1. Posse\n\n---\n\n## 1. Posse\n\n> A posse exige **corpus** e **animus**."
    response = client.post(
        f"/lessons/{lesson_id}/colar-guia", data={"resposta": resposta}, follow_redirects=True
    )
    assert response.status_code == 200
    assert response.url.path == f"/lessons/{lesson_id}/guia"
    assert "<strong>corpus</strong>" in response.text
    assert "<blockquote>" in response.text

    with holder.SessionLocal() as session:
        from app.models import Lesson

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_md.startswith("# Aula sem título identificado")
        assert lesson.guia_gerado_em is not None


def test_colar_guia_strips_chatter_before_the_title(app_env):
    """O parser corta a partir do primeiro '# ' -- conversa de chat em
    volta ("aqui está o resultado:") não deve virar parte do guia."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    resposta = "Claro, aqui está o guia organizado:\n\n# Aula de Posse\n\nConteúdo real aqui."
    client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": resposta})

    with holder.SessionLocal() as session:
        from app.models import Lesson

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_md == "# Aula de Posse\n\nConteúdo real aqui."
        assert "Claro, aqui está" not in lesson.guia_md


def test_colar_guia_rejects_empty_response(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    response = client.post(
        f"/lessons/{lesson_id}/colar-guia", data={"resposta": "   "}, follow_redirects=True
    )
    assert "erro" in str(response.url)

    with holder.SessionLocal() as session:
        from app.models import Lesson

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_md is None


def test_colar_guia_logs_ai_call_as_manual_and_free(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": "# Guia\n\nconteúdo"})

    with holder.SessionLocal() as session:
        from app.models import AiCall

        call = session.scalar(select(AiCall).where(AiCall.lesson_id == lesson_id))
        assert call.tipo_acao == "guia_aula"
        assert call.via == "manual"
        assert call.custo_usd == 0.0


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

    client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": "# Guia\n\nconteúdo real"})

    response = client.get(f"/lessons/{lesson_id}/guia.md")
    assert response.status_code == 200
    assert response.text.strip() == "# Guia\n\nconteúdo real"
    assert "Content-Disposition" in response.headers


def test_lesson_detail_shows_generate_guia_button_before_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/guia-pacote.md" in response.text
    assert f"/lessons/{lesson_id}/colar-guia" in response.text


def test_lesson_detail_shows_view_guia_button_after_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": "# Guia\n\nconteúdo"})

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/guia\"" in response.text
