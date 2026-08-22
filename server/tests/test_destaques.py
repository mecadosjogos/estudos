import json
import subprocess
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _lesson_with_transcript_id(session, titulo="Aula destaques") -> int:
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


def _pasted_response():
    payload = {
        "resumo": "R.",
        "aula_editada": [
            {"tipo": "destaque-prova", "texto": "Isso cai na prova, prestem atenção.", "start_s": 0.0, "end_s": 3.0},
            {"tipo": "ditado", "texto": "Anotem isso com calma.", "start_s": 3.0, "end_s": 4.5},
            {"tipo": "normal", "texto": "Segue o resto da explicação.", "start_s": 4.5, "end_s": 5.0},
        ],
        "indice": [], "guia_md": "# G", "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _write_real_mp3(path, duration_s=5):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}",
        "-ar", "16000", "-ac", "1", "-b:a", "32k", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_list_destaques_shows_only_destaque_and_ditado_blocks(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    response = client.get("/destaques")
    assert response.status_code == 200
    assert "Isso cai na prova" in response.text
    assert "Anotem isso com calma" in response.text
    assert "Segue o resto da explicação" not in response.text


def test_clip_audio_cuts_and_serves_real_mp3(app_env):
    from app import config

    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import EditedBlock

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    _write_real_mp3(config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3")

    with holder.SessionLocal() as session:
        block_id = session.scalar(
            select(EditedBlock.id).where(EditedBlock.lesson_id == lesson_id, EditedBlock.tipo == "destaque-prova")
        )

    response = client.get(f"/destaques/{block_id}/clip.mp3")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert len(response.content) > 0

    clip_files = list(config.DESTAQUES_CLIPS_DIR.glob(f"bloco-{block_id}-*.mp3"))
    assert len(clip_files) == 1


def test_clip_audio_404_for_non_destaque_block(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import EditedBlock

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    with holder.SessionLocal() as session:
        block_id = session.scalar(
            select(EditedBlock.id).where(EditedBlock.lesson_id == lesson_id, EditedBlock.tipo == "normal")
        )

    response = client.get(f"/destaques/{block_id}/clip.mp3")
    assert response.status_code == 404


def test_clip_audio_404_without_lesson_mp3(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import EditedBlock

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    with holder.SessionLocal() as session:
        block_id = session.scalar(
            select(EditedBlock.id).where(EditedBlock.lesson_id == lesson_id, EditedBlock.tipo == "destaque-prova")
        )

    response = client.get(f"/destaques/{block_id}/clip.mp3")
    assert response.status_code == 404
