import json
import threading
from datetime import date, datetime, timedelta, timezone

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _make_lesson_with_segment(session, titulo="Aula"):
    from sqlalchemy import select

    from app.models import AudioSegment, Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    segment = AudioSegment(
        lesson_id=lesson.id,
        ordem=1,
        original_filename="aula.mp3",
        storage_path="data/media/original/fake.mp3",
        size_bytes=10,
        status="complete",
    )
    session.add(segment)
    session.commit()
    return lesson.id


def test_claim_next_job_is_atomic_across_threads(app_env):
    from app.db import holder
    from app.models import TranscriptionJob
    from app.routes.jobs import claim_next_job

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    results = []
    barrier = threading.Barrier(2)

    def run(name):
        barrier.wait()
        with holder.SessionLocal() as session:
            job = claim_next_job(session, name, "gpu_worker")
            results.append(job.id if job else None)

    threads = [threading.Thread(target=run, args=(f"worker-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    assert len(winners) == 1


def test_stale_claim_gets_reclaimed(app_env):
    from app.db import holder
    from app.models import TranscriptionJob
    from app.routes.jobs import claim_next_job

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        stale = TranscriptionJob(
            lesson_id=lesson_id,
            target="gpu_worker",
            status="claimed",
            claim_token="old-token",
            claimed_by="worker-que-travou",
            claimed_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        )
        session.add(stale)
        session.commit()
        job_id = stale.id

    with holder.SessionLocal() as session:
        reclaimed = claim_next_job(session, "worker-novo", "gpu_worker")

    assert reclaimed is not None
    assert reclaimed.id == job_id
    assert reclaimed.claimed_by == "worker-novo"


def test_next_job_endpoint_returns_download_urls(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    response = client.get("/api/jobs/next", params={"worker_name": "desktop-4070"})
    assert response.status_code == 200
    job = response.json()["job"]
    assert job is not None
    assert job["lesson_id"] == lesson_id
    assert len(job["segments"]) == 1
    assert "/download" in job["segments"][0]["download_url"]


def test_next_job_returns_none_when_empty(app_env):
    client = _authed_client()
    response = client.get("/api/jobs/next", params={"worker_name": "x"})
    assert response.status_code == 200
    assert response.json()["job"] is None


def test_result_submission_is_idempotent(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Transcript, TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    claim = client.get("/api/jobs/next", params={"worker_name": "desktop-4070"}).json()["job"]

    payload = json.dumps({
        "full_text": "ola mundo",
        "segments": [{"idx": 0, "start_s": 0.0, "end_s": 1.0, "text": "ola mundo", "words": []}],
    })
    form = {
        "claim_token": claim["claim_token"],
        "worker_name": "desktop-4070",
        "engine": "faster-whisper-large-v3",
        "duration_s": "1.0",
    }
    files = {"audio": ("a.mp3", b"fake-mp3"), "payload": ("payload.json", payload)}
    first = client.post(f"/api/jobs/{claim['id']}/result", data=form, files=files)
    assert first.status_code == 200
    assert first.json() == {"ok": True, "already_received": False}

    with holder.SessionLocal() as session:
        assert session.query(Transcript).filter_by(lesson_id=lesson_id).count() == 1

    # reenvio depois de um timeout de rede: mesmo claim_token, não duplica
    second = client.post(f"/api/jobs/{claim['id']}/result", data=form, files=files)
    assert second.status_code == 200
    assert second.json() == {"ok": True, "already_received": True}

    with holder.SessionLocal() as session:
        assert session.query(Transcript).filter_by(lesson_id=lesson_id).count() == 1

    with holder.SessionLocal() as session:
        job = session.get(TranscriptionJob, claim["id"])
        assert job.status == "done"


def test_enqueue_pending_transcriptions_finds_audio_without_transcript(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)

    response = client.post("/api/jobs/enqueue-pending-transcriptions")
    assert response.status_code == 200
    assert response.json()["enqueued"] == [{"lesson_id": lesson_id, "titulo": "Aula"}]

    with holder.SessionLocal() as session:
        jobs = session.scalars(
            select(TranscriptionJob).where(TranscriptionJob.lesson_id == lesson_id)
        ).all()
        assert len(jobs) == 1
        assert jobs[0].status == "pending"
        assert jobs[0].target == "gpu_worker"


def test_enqueue_pending_transcriptions_skips_lixo_subject(app_env):
    client = _authed_client()
    from datetime import date

    from app.db import holder
    from app.models import AudioSegment, Lesson, Subject

    with holder.SessionLocal() as session:
        lixo = Subject(nome="Lixo", sigla="LIXO")
        session.add(lixo)
        session.flush()
        lesson = Lesson(subject_id=lixo.id, titulo="Aula de teste", data=date(2026, 3, 12))
        session.add(lesson)
        session.flush()
        session.add(AudioSegment(
            lesson_id=lesson.id, ordem=1, original_filename="a.m4a",
            storage_path="/tmp/x", size_bytes=10, status="complete",
        ))
        session.commit()

    response = client.post("/api/jobs/enqueue-pending-transcriptions")
    assert response.status_code == 200
    assert response.json()["enqueued"] == []


def test_enqueue_pending_transcriptions_skips_lesson_without_audio(app_env):
    client = _authed_client()
    from datetime import date

    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem áudio", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()

    response = client.post("/api/jobs/enqueue-pending-transcriptions")
    assert response.json()["enqueued"] == []


def test_enqueue_pending_transcriptions_skips_lesson_that_already_has_transcript(app_env):
    client = _authed_client()
    from datetime import date

    from sqlalchemy import select

    from app.db import holder
    from app.models import AudioSegment, Lesson, Subject, Transcript

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Já transcrita", data=date(2026, 3, 12))
        session.add(lesson)
        session.flush()
        session.add(AudioSegment(
            lesson_id=lesson.id, ordem=1, original_filename="a.m4a",
            storage_path="/tmp/x", size_bytes=10, status="complete",
        ))
        session.add(Transcript(lesson_id=lesson.id, engine="e", worker_name="w", full_text="x", duration_s=1.0))
        session.commit()

    response = client.post("/api/jobs/enqueue-pending-transcriptions")
    assert response.json()["enqueued"] == []


def test_enqueue_pending_transcriptions_is_idempotent(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        _make_lesson_with_segment(session)

    client.post("/api/jobs/enqueue-pending-transcriptions")
    client.post("/api/jobs/enqueue-pending-transcriptions")

    with holder.SessionLocal() as session:
        jobs = session.scalars(select(TranscriptionJob)).all()
        assert len(jobs) == 1


def test_result_submission_accepts_payload_over_1mb(app_env):
    """Regressão real: uma aula de ~2h gera milhares de segmentos com
    timestamp por palavra, passando fácil de 1MB de JSON. O Starlette
    limita CAMPO de formulário a 1MB — só passou a funcionar depois de o
    payload virar parte de arquivo no multipart, não campo de texto."""
    client = _authed_client()
    from app.db import holder
    from app.models import Transcript

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        from app.models import TranscriptionJob

        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    claim = client.get("/api/jobs/next", params={"worker_name": "desktop-4070"}).json()["job"]

    # ~2500 segmentos com palavras -- facilmente > 1MB de JSON, como numa
    # aula real de ~2h.
    segments = [
        {
            "idx": i, "start_s": float(i), "end_s": float(i + 1),
            "text": "uma frase de teste razoavelmente longa para inflar o payload",
            "words": [{"text": "palavra", "start_s": float(i), "end_s": float(i) + 0.5, "probability": 0.9}] * 8,
        }
        for i in range(2500)
    ]
    payload = json.dumps({"full_text": "x" * 1000, "segments": segments})
    assert len(payload.encode("utf-8")) > 1024 * 1024  # confirma que o teste testa o cenário real

    form = {
        "claim_token": claim["claim_token"], "worker_name": "desktop-4070",
        "engine": "faster-whisper-large-v3", "duration_s": "6661.0",
    }
    files = {"audio": ("a.mp3", b"fake-mp3"), "payload": ("payload.json", payload)}
    response = client.post(f"/api/jobs/{claim['id']}/result", data=form, files=files)

    assert response.status_code == 200
    with holder.SessionLocal() as session:
        transcript = session.query(Transcript).filter_by(lesson_id=lesson_id).first()
        assert transcript is not None
        assert len(transcript.segments) == 2500


def test_result_submission_rejects_wrong_claim_token(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    claim = client.get("/api/jobs/next", params={"worker_name": "desktop-4070"}).json()["job"]

    form = {
        "claim_token": "token-errado",
        "worker_name": "desktop-4070",
        "engine": "faster-whisper-large-v3",
        "duration_s": "1.0",
    }
    files = {
        "audio": ("a.mp3", b"fake-mp3"),
        "payload": ("payload.json", json.dumps({"full_text": "x", "segments": []})),
    }
    response = client.post(f"/api/jobs/{claim['id']}/result", data=form, files=files)
    assert response.status_code == 409


def test_original_deleted_from_vps_after_successful_result(app_env, tmp_path):
    client = _authed_client()
    from app import config
    from app.db import holder
    from app.models import AudioSegment, Lesson, Subject, TranscriptionJob
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Aula com arquivo real", data=date(2026, 3, 12))
        session.add(lesson)
        session.flush()

        real_original = config.MEDIA_ORIGINAL_DIR / "real-test.mp3"
        real_original.parent.mkdir(parents=True, exist_ok=True)
        real_original.write_bytes(b"conteudo de audio")

        segment = AudioSegment(
            lesson_id=lesson.id, ordem=1, original_filename="a.mp3",
            storage_path=str(real_original),
            size_bytes=18, status="complete",
        )
        session.add(segment)
        session.add(TranscriptionJob(lesson_id=lesson.id, target="gpu_worker"))
        session.commit()
        lesson_id = lesson.id

    assert real_original.exists()

    claim = client.get("/api/jobs/next", params={"worker_name": "w"}).json()["job"]
    form = {
        "claim_token": claim["claim_token"], "worker_name": "w",
        "engine": "e", "duration_s": "1.0",
    }
    files = {
        "audio": ("a.mp3", b"fake"),
        "payload": ("payload.json", json.dumps({"full_text": "x", "segments": []})),
    }
    client.post(f"/api/jobs/{claim['id']}/result", data=form, files=files)

    assert not real_original.exists()


def test_fail_endpoint_marks_job_failed(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    claim = client.get("/api/jobs/next", params={"worker_name": "w"}).json()["job"]
    response = client.post(
        f"/api/jobs/{claim['id']}/fail",
        json={"claim_token": claim["claim_token"], "error": "GPU sem memória"},
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        job = session.get(TranscriptionJob, claim["id"])
        assert job.status == "failed"
        assert job.error == "GPU sem memória"


def test_download_requires_matching_job_and_segment(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)
        session.add(TranscriptionJob(lesson_id=lesson_id, target="gpu_worker"))
        session.commit()

    claim = client.get("/api/jobs/next", params={"worker_name": "w"}).json()["job"]
    segment_id = claim["segments"][0]["id"]

    ok = client.get(f"/api/jobs/{claim['id']}/segments/{segment_id}/download")
    assert ok.status_code in (200, 410)  # 410 se o arquivo fake não existir de fato

    wrong = client.get(f"/api/jobs/{claim['id']}/segments/999999/download")
    assert wrong.status_code == 404


def test_direct_upload_auto_enqueues_transcription(app_env):
    from starlette.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/uploads/direct",
        data={"subject_sigla": "TGC", "titulo": "Nota", "data": "2026-04-02"},
        files={"file": ("nota.m4a", b"conteudo", "audio/m4a")},
        headers={"Authorization": "Bearer test-token"},
    )
    lesson_id = response.json()["lesson_id"]

    from app.db import holder
    from app.models import TranscriptionJob
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        jobs = session.scalars(
            select(TranscriptionJob).where(TranscriptionJob.lesson_id == lesson_id)
        ).all()
    assert len(jobs) == 1
    assert jobs[0].status == "pending"
    assert jobs[0].target == "gpu_worker"


def test_enqueue_transcription_does_not_duplicate_pending_job(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)

    client.post(f"/api/lessons/{lesson_id}/enqueue-transcription")
    client.post(f"/api/lessons/{lesson_id}/enqueue-transcription")

    with holder.SessionLocal() as session:
        jobs = session.scalars(
            select(TranscriptionJob).where(TranscriptionJob.lesson_id == lesson_id)
        ).all()
    assert len(jobs) == 1


def test_lesson_with_audio_but_no_job_offers_start_button(app_env):
    """Bug real: aula com segmentos de áudio subidos antes de o enfileiramento
    automático existir (ou por qualquer outro motivo sem job) tinha que dar
    pra iniciar a transcrição na mão — a página não podia ficar sem ação."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)

    page = client.get(f"/lessons/{lesson_id}")
    assert "iniciar-transcricao" in page.text
    assert "transcrever-na-vps" in page.text


def test_iniciar_transcricao_creates_pending_job(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)

    response = client.post(f"/lessons/{lesson_id}/iniciar-transcricao", follow_redirects=True)
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        jobs = session.scalars(
            select(TranscriptionJob).where(TranscriptionJob.lesson_id == lesson_id)
        ).all()
    assert len(jobs) == 1
    assert jobs[0].status == "pending"
    assert jobs[0].target == "gpu_worker"


def test_iniciar_transcricao_rejects_lesson_without_audio(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem audio", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    response = client.post(f"/lessons/{lesson_id}/iniciar-transcricao")
    assert response.status_code == 400


def test_gpu_and_vps_queues_are_independent(app_env):
    """Uma aula pode ter um job pendente de GPU e, ao mesmo tempo, um da VPS
    acionado manualmente — não é a mesma fila."""
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_lesson_with_segment(session)

    client.post(f"/lessons/{lesson_id}/iniciar-transcricao")
    client.post(f"/lessons/{lesson_id}/transcrever-na-vps")

    with holder.SessionLocal() as session:
        jobs = session.scalars(
            select(TranscriptionJob).where(TranscriptionJob.lesson_id == lesson_id)
        ).all()
    targets = sorted(j.target for j in jobs)
    assert targets == ["gpu_worker", "vps_cpu"]
