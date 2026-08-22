import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _lesson_with_transcript_id(session, titulo="Aula dissertativa") -> int:
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    transcript = Transcript(
        lesson_id=lesson.id, engine="e", worker_name="w",
        full_text="a posse exige corpus e animus, elementos objetivo e subjetivo", duration_s=5.0,
    )
    session.add(transcript)
    session.flush()
    session.add(TranscriptSegment(
        transcript_id=transcript.id, idx=0, start_s=0.0, end_s=5.0,
        text="a posse exige corpus e animus", words_json="[]",
    ))
    session.commit()
    return lesson.id


def _pasted_question_response():
    payload = {
        "enunciado": "João encontra um relógio perdido e passa a usá-lo como se fosse seu. Discorra sobre a natureza jurídica dessa situação.",
        "rubrica": ["corpus", "animus", "elemento objetivo", "elemento subjetivo"],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _pasted_correction_response():
    payload = {
        "pontos_cobertos": ["corpus", "animus"],
        "pontos_faltantes": ["elemento subjetivo"],
        "comentario": "Faltou detalhar o elemento subjetivo da posse.",
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_generate_question_from_lesson_automatic_without_api_key_shows_error(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.post(f"/lessons/{lesson_id}/dissertativas/gerar", follow_redirects=True)
    assert response.status_code == 200
    assert "erro_ia" in str(response.url)


def test_download_generation_package_from_lesson(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.get(f"/lessons/{lesson_id}/dissertativas/gerar-pacote.md")
    assert response.status_code == 200
    assert "corpus e animus" in response.text
    assert "Content-Disposition" in response.headers


def test_colar_questao_from_lesson_creates_question(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import DissertativaQuestion

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.post(
        f"/lessons/{lesson_id}/dissertativas/colar-questao",
        data={"resposta": _pasted_question_response()},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "relógio perdido" in response.text
    assert "corpus" in response.text

    with holder.SessionLocal() as session:
        question = session.scalar(select(DissertativaQuestion).where(DissertativaQuestion.lesson_id == lesson_id))
        assert question is not None
        assert question.subject_id is not None
        assert json.loads(question.rubrica_json) == ["corpus", "animus", "elemento objetivo", "elemento subjetivo"]


def test_colar_questao_invalida_mostra_erro(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.post(
        f"/lessons/{lesson_id}/dissertativas/colar-questao",
        data={"resposta": "isso não é json"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "erro" in str(response.url)


def test_generate_from_assunto_without_linked_lessons_shows_error(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.assuntos import find_or_create_assunto

    with holder.SessionLocal() as session:
        assunto = find_or_create_assunto(session, "Posse dissertativa")
        session.commit()
        assunto_id = assunto.id

    response = client.post(f"/assuntos/{assunto_id}/dissertativas/gerar", follow_redirects=True)
    assert response.status_code == 200
    assert "erro_ia" in str(response.url)


def test_colar_questao_from_assunto_creates_question_without_subject(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.assuntos import ensure_cobertura, find_or_create_assunto
    from app.models import DissertativaQuestion, LessonAssunto, Subject

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        assunto = find_or_create_assunto(session, "Posse dissertativa 2")
        ensure_cobertura(session, assunto.id, subject_id)
        session.add(LessonAssunto(
            lesson_id=lesson_id, deriv_key="assunto:posse-dissertativa-2",
            texto_proposto="Posse dissertativa 2", assunto_id=assunto.id, status="aceito",
        ))
        session.commit()
        assunto_id = assunto.id

    response = client.post(
        f"/assuntos/{assunto_id}/dissertativas/colar-questao",
        data={"resposta": _pasted_question_response()},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "relógio perdido" in response.text

    with holder.SessionLocal() as session:
        question = session.scalar(select(DissertativaQuestion).where(DissertativaQuestion.assunto_id == assunto_id))
        assert question is not None
        assert question.subject_id is None
        assert question.lesson_id is None


def test_responder_e_corrigir_via_colar_correcao(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import DissertativaAttempt, DissertativaQuestion

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/dissertativas/colar-questao", data={"resposta": _pasted_question_response()})

    with holder.SessionLocal() as session:
        question_id = session.scalar(select(DissertativaQuestion.id).where(DissertativaQuestion.lesson_id == lesson_id))

    response = client.post(
        f"/dissertativas/{question_id}/responder",
        data={"resposta_texto": "É posse, pois há corpus e animus de dono."},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "É posse, pois há corpus e animus de dono." in response.text

    with holder.SessionLocal() as session:
        attempt_id = session.scalar(select(DissertativaAttempt.id).where(DissertativaAttempt.question_id == question_id))
        assert session.get(DissertativaAttempt, attempt_id).status == "respondido"

    response = client.get(f"/dissertativas/{question_id}/attempts/{attempt_id}/prompt.md")
    assert response.status_code == 200
    assert "É posse, pois há corpus e animus de dono." in response.text
    assert "corpus" in response.text

    response = client.post(
        f"/dissertativas/{question_id}/attempts/{attempt_id}/colar-correcao",
        data={"resposta": _pasted_correction_response()},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "elemento subjetivo" in response.text
    assert "Faltou detalhar" in response.text

    with holder.SessionLocal() as session:
        attempt = session.get(DissertativaAttempt, attempt_id)
        assert attempt.status == "avaliado"
        assert attempt.ai_call_id is not None


def test_correct_automatically_without_api_key_shows_error(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import DissertativaAttempt, DissertativaQuestion

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/dissertativas/colar-questao", data={"resposta": _pasted_question_response()})

    with holder.SessionLocal() as session:
        question_id = session.scalar(select(DissertativaQuestion.id).where(DissertativaQuestion.lesson_id == lesson_id))

    client.post(f"/dissertativas/{question_id}/responder", data={"resposta_texto": "resposta qualquer"})

    with holder.SessionLocal() as session:
        attempt_id = session.scalar(select(DissertativaAttempt.id).where(DissertativaAttempt.question_id == question_id))

    response = client.post(f"/dissertativas/{question_id}/attempts/{attempt_id}/avaliar", follow_redirects=True)
    assert response.status_code == 200
    assert "erro_ia" in str(response.url)


def test_dissertativas_list_and_lesson_entry_point(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/dissertativas/colar-questao", data={"resposta": _pasted_question_response()})

    response = client.get("/dissertativas")
    assert response.status_code == 200
    assert "relógio perdido" in response.text

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/dissertativas/gerar" in response.text
