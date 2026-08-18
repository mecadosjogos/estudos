from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _tgdc_id():
    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        return session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))


def test_upload_page_requires_session(app_env):
    from starlette.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/upload")
    assert response.status_code == 401


def test_chunked_upload_end_to_end_creates_audio_segment(app_env):
    client = _authed_client()
    subject_id = _tgdc_id()

    lesson_response = client.post(
        "/api/lessons",
        data={"subject_id": subject_id, "titulo": "Aula gravada", "data": "2026-03-12"},
    )
    lesson_id = lesson_response.json()["id"]

    upload_id = "test-upload-001"
    content = b"x" * (5 * 1024 * 1024 + 123)  # força mais de um chunk de 4MB
    chunk_size = 4 * 1024 * 1024
    total_chunks = -(-len(content) // chunk_size)

    init = client.post(
        "/api/uploads/init",
        json={
            "upload_id": upload_id,
            "lesson_id": lesson_id,
            "ordem": 1,
            "filename": "aula.m4a",
            "total_chunks": total_chunks,
        },
    )
    assert init.status_code == 200
    assert init.json()["received_chunks"] == []

    for i in range(total_chunks):
        chunk = content[i * chunk_size : (i + 1) * chunk_size]
        resp = client.put(f"/api/uploads/{upload_id}/chunks/{i}", content=chunk)
        assert resp.status_code == 200

    complete = client.post(f"/api/uploads/{upload_id}/complete")
    assert complete.status_code == 200
    segment_id = complete.json()["segment_id"]

    from app.db import holder
    from app.models import AudioSegment

    with holder.SessionLocal() as session:
        segment = session.get(AudioSegment, segment_id)
        assert segment.lesson_id == lesson_id
        assert segment.size_bytes == len(content)
        assert segment.status == "complete"

        from app import config

        stored = config.BASE_DIR / segment.storage_path
        assert stored.exists()
        assert stored.read_bytes() == content


def test_upload_resumes_after_partial_chunks(app_env):
    client = _authed_client()
    subject_id = _tgdc_id()
    lesson_id = client.post(
        "/api/lessons", data={"subject_id": subject_id, "titulo": "Aula 2", "data": "2026-03-19"}
    ).json()["id"]

    upload_id = "test-upload-resume"
    chunk_size = 4 * 1024 * 1024
    content = b"y" * (chunk_size * 2)

    client.post(
        "/api/uploads/init",
        json={
            "upload_id": upload_id,
            "lesson_id": lesson_id,
            "ordem": 1,
            "filename": "aula.mp3",
            "total_chunks": 2,
        },
    )
    client.put(f"/api/uploads/{upload_id}/chunks/0", content=content[:chunk_size])

    # simula reconexão: cliente reabre a página e reinicia o mesmo upload_id
    resumed = client.post(
        "/api/uploads/init",
        json={
            "upload_id": upload_id,
            "lesson_id": lesson_id,
            "ordem": 1,
            "filename": "aula.mp3",
            "total_chunks": 2,
        },
    )
    assert resumed.json()["received_chunks"] == [0]

    client.put(f"/api/uploads/{upload_id}/chunks/1", content=content[chunk_size:])
    complete = client.post(f"/api/uploads/{upload_id}/complete")
    assert complete.status_code == 200


def test_complete_fails_if_chunks_missing(app_env):
    client = _authed_client()
    subject_id = _tgdc_id()
    lesson_id = client.post(
        "/api/lessons", data={"subject_id": subject_id, "titulo": "Aula 3", "data": "2026-03-26"}
    ).json()["id"]

    upload_id = "test-upload-incomplete"
    client.post(
        "/api/uploads/init",
        json={
            "upload_id": upload_id,
            "lesson_id": lesson_id,
            "ordem": 1,
            "filename": "aula.wav",
            "total_chunks": 2,
        },
    )
    client.put(f"/api/uploads/{upload_id}/chunks/0", content=b"only chunk")

    response = client.post(f"/api/uploads/{upload_id}/complete")
    assert response.status_code == 409


def test_rejects_disallowed_extension(app_env):
    client = _authed_client()
    subject_id = _tgdc_id()
    lesson_id = client.post(
        "/api/lessons", data={"subject_id": subject_id, "titulo": "Aula 4", "data": "2026-04-01"}
    ).json()["id"]

    response = client.post(
        "/api/uploads/init",
        json={
            "upload_id": "test-upload-badext",
            "lesson_id": lesson_id,
            "ordem": 1,
            "filename": "aula.exe",
            "total_chunks": 1,
        },
    )
    assert response.status_code == 400
    assert ".exe" in response.json()["detail"]


def test_accepts_common_audio_and_video_extensions(app_env):
    client = _authed_client()
    subject_id = _tgdc_id()
    lesson_id = client.post(
        "/api/lessons", data={"subject_id": subject_id, "titulo": "Aula 5", "data": "2026-04-05"}
    ).json()["id"]

    for i, ext in enumerate(["opus", "aac", "mp4", "mov", "ogg", "flac", "webm", "3gp"]):
        response = client.post(
            "/api/uploads/init",
            json={
                "upload_id": f"test-upload-{ext}",
                "lesson_id": lesson_id,
                "ordem": i + 1,
                "filename": f"nota.{ext}",
                "total_chunks": 1,
            },
        )
        assert response.status_code == 200


def test_direct_upload_with_bearer_token_creates_lesson_and_segment(app_env):
    from starlette.testclient import TestClient

    from app.main import app

    client = TestClient(app)  # sem cookie de sessão
    response = client.post(
        "/api/uploads/direct",
        data={"subject_sigla": "TGC", "titulo": "Explicação rápida", "data": "2026-04-02"},
        files={"file": ("nota.m4a", b"conteudo de audio curto", "audio/m4a")},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()

    from sqlalchemy import select

    from app.db import holder
    from app.models import AudioSegment, Lesson

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, body["lesson_id"])
        assert lesson.titulo == "Explicação rápida"
        segment = session.scalar(select(AudioSegment).where(AudioSegment.lesson_id == lesson.id))
        assert segment.original_filename == "nota.m4a"


def test_direct_upload_without_token_is_rejected(app_env):
    from starlette.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/uploads/direct",
        data={"subject_sigla": "TGC", "titulo": "x", "data": "2026-04-02"},
        files={"file": ("nota.m4a", b"conteudo", "audio/m4a")},
    )
    assert response.status_code == 401
