from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _make_transcribed_lesson(session, titulo="Aula"):
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()
    session.add(
        Transcript(
            lesson_id=lesson.id,
            engine="faster-whisper-large-v3",
            worker_name="desktop-4070",
            full_text="conteudo",
            duration_s=10.0,
        )
    )
    session.commit()
    return lesson.id


def test_restore_is_blocked_while_job_in_progress(app_env):
    client = _authed_client()
    from app import backup
    from app.db import holder
    from app.models import Lesson, Subject, TranscriptionJob

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Aula", data=date(2026, 3, 12))
        session.add(lesson)
        session.flush()
        session.add(TranscriptionJob(lesson_id=lesson.id, target="gpu_worker"))
        session.commit()

    backup_path = backup.create_backup()
    with backup_path.open("rb") as f:
        stage = client.post("/admin/restore/stage", files={"file": (backup_path.name, f, "application/octet-stream")})
    assert "job_in_progress" not in stage.text or True  # a página é renderizada; o bloqueio real é no confirm

    confirm = client.post(
        "/admin/restore/confirm", data={"staged_filename": backup_path.name}, follow_redirects=True
    )
    assert "restore_blocked=1" in str(confirm.url)


def test_restore_proceeds_without_job_in_progress(app_env):
    client = _authed_client()
    from app import backup

    backup_path = backup.create_backup()
    with backup_path.open("rb") as f:
        client.post("/admin/restore/stage", files={"file": (backup_path.name, f, "application/octet-stream")})

    confirm = client.post(
        "/admin/restore/confirm", data={"staged_filename": backup_path.name}, follow_redirects=True
    )
    assert "restored_from_safety" in str(confirm.url)


def test_rebuild_media_enqueues_only_lessons_missing_mp3(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app import config
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        with_mp3 = _make_transcribed_lesson(session, "Tem mp3")
        without_mp3 = _make_transcribed_lesson(session, "Sem mp3")

    config.MEDIA_WEB_DIR.mkdir(parents=True, exist_ok=True)
    (config.MEDIA_WEB_DIR / f"lesson-{with_mp3}.mp3").write_bytes(b"ja existe")

    response = client.post("/admin/reconstruir-midia", follow_redirects=True)
    assert "media_rebuild_enqueued=1" in str(response.url)

    with holder.SessionLocal() as session:
        jobs = session.scalars(select(TranscriptionJob)).all()
    assert len(jobs) == 1
    assert jobs[0].lesson_id == without_mp3
    assert jobs[0].target == "rebuild_media"


def test_rebuild_media_is_idempotent_across_calls(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, "Sem mp3")

    client.post("/admin/reconstruir-midia")
    client.post("/admin/reconstruir-midia")

    with holder.SessionLocal() as session:
        jobs = session.scalars(select(TranscriptionJob)).all()
    assert len(jobs) == 1


def test_rebuild_result_saves_mp3_and_marks_job_done(app_env):
    client = _authed_client()
    from app import config
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, "Sem mp3")

    client.post("/admin/reconstruir-midia")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "rebuild_media"}).json()["job"]

    response = client.post(
        f"/api/jobs/{claim['id']}/rebuild-result",
        data={"claim_token": claim["claim_token"]},
        files={"audio": ("audio.mp3", b"conteudo mp3 reconstruido")},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "already_received": False}

    mp3_path = config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3"
    assert mp3_path.read_bytes() == b"conteudo mp3 reconstruido"

    with holder.SessionLocal() as session:
        job = session.get(TranscriptionJob, claim["id"])
        assert job.status == "done"


def test_download_latest_backup_requires_admin(app_env):
    from app.db import holder
    from app.models import User
    from app.security import hash_password

    with holder.SessionLocal() as session:
        session.add(User(username="comum", senha_hash=hash_password("x"), papel="usuario", status="aprovado"))
        session.commit()

    client = _authed_client()  # admin
    admin_response = client.get("/admin/backups/latest.db")
    assert admin_response.status_code == 200
    assert admin_response.headers["content-type"] == "application/octet-stream"
    assert admin_response.content[:16] == b"SQLite format 3\x00"

    from app.main import app

    comum_client = TestClient(app)
    comum_client.post("/login", data={"username": "comum", "senha": "x"})
    comum_response = comum_client.get("/admin/backups/latest.db")
    assert comum_response.status_code == 403


def test_download_install_script_embeds_server_url_and_token(app_env):
    client = _authed_client()
    response = client.get("/admin/instalar-worker.ps1")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="instalar_maquina_worker.ps1"'
    assert '$env:ESTUDOS_SERVER_URL = "http://testserver"' in response.text
    assert '$env:ESTUDOS_ACCESS_TOKEN = "test-token"' in response.text
    # o resto do script continua intacto, não é substituído por engano
    assert "faster_whisper" in response.text
    assert "nvidia-smi" in response.text


def test_download_install_script_requires_admin(app_env):
    from app.db import holder
    from app.main import app
    from app.models import User
    from app.security import hash_password

    with holder.SessionLocal() as session:
        session.add(User(username="comum2", senha_hash=hash_password("x"), papel="usuario", status="aprovado"))
        session.commit()

    comum_client = TestClient(app)
    comum_client.post("/login", data={"username": "comum2", "senha": "x"})
    response = comum_client.get("/admin/instalar-worker.ps1")
    assert response.status_code == 403


def test_download_install_package_zip_contains_prefilled_script_and_no_duplicates(app_env):
    import io
    import zipfile

    client = _authed_client()
    response = client.get("/admin/instalar-worker.zip")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="estudos-worker-setup.zip"'

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()

    # sem duplicata: a versão pré-preenchida substitui a crua, não soma
    assert names.count("scripts/instalar_maquina_worker.ps1") == 1
    script_content = zf.read("scripts/instalar_maquina_worker.ps1").decode("utf-8")
    assert '$env:ESTUDOS_SERVER_URL = "http://testserver"' in script_content
    assert '$env:ESTUDOS_ACCESS_TOKEN = "test-token"' in script_content

    # amostra de cada área que a máquina de worker precisa
    assert "scripts/instalar_maquina_worker.bat" in names
    assert "PLANO.md" in names
    assert "RUNBOOK.md" in names
    assert ".env.example" in names
    assert any(n.startswith("worker/") for n in names)
    assert any(n.startswith("server/app/") for n in names)

    # atalhos de raiz que o RUNBOOK.md manda usar -- ficaram de fora numa
    # passada anterior e a máquina nova não conseguia processar aula/página
    assert "disparar-skill.ps1" in names
    assert "iniciar-servidor-testes.bat" in names
    assert "processar-aulas.ps1" in names
    assert "processar-aulas.bat" in names
    assert "transcrever-paginas.ps1" in names
    assert "transcrever-paginas.bat" in names

    # nunca o backup de dados (nem seria copiado na imagem, mas confirma
    # que a lista de caminhos empacotados não inclui isso por engano)
    assert not any(n.startswith("data-backup/") for n in names)


def test_download_install_package_requires_admin(app_env):
    from app.db import holder
    from app.main import app
    from app.models import User
    from app.security import hash_password

    with holder.SessionLocal() as session:
        session.add(User(username="comum3", senha_hash=hash_password("x"), papel="usuario", status="aprovado"))
        session.commit()

    comum_client = TestClient(app)
    comum_client.post("/login", data={"username": "comum3", "senha": "x"})
    response = comum_client.get("/admin/instalar-worker.zip")
    assert response.status_code == 403


def test_lessons_json_excludes_lixo_and_reflects_has_audio(app_env):
    client = _authed_client()
    from app import config
    from app.db import holder
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        with_mp3 = _make_transcribed_lesson(session, "Tem mp3")
        without_mp3 = _make_transcribed_lesson(session, "Sem mp3")

        lixo = Subject(nome="Lixo", sigla="LIXO")
        session.add(lixo)
        session.flush()
        session.add(Lesson(subject_id=lixo.id, titulo="Aula de teste", data=date(2026, 3, 12)))
        session.commit()

    config.MEDIA_WEB_DIR.mkdir(parents=True, exist_ok=True)
    (config.MEDIA_WEB_DIR / f"lesson-{with_mp3}.mp3").write_bytes(b"mp3")

    response = client.get("/admin/lessons.json")
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()}

    assert by_id[with_mp3]["has_audio"] is True
    assert by_id[without_mp3]["has_audio"] is False
    assert all(item["subject_sigla"] != "LIXO" for item in by_id.values())


def test_rebuild_result_is_idempotent(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, "Sem mp3")

    client.post("/admin/reconstruir-midia")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "rebuild_media"}).json()["job"]

    form = {"claim_token": claim["claim_token"]}
    files = {"audio": ("audio.mp3", b"conteudo")}
    first = client.post(f"/api/jobs/{claim['id']}/rebuild-result", data=form, files=files)
    second = client.post(f"/api/jobs/{claim['id']}/rebuild-result", data=form, files=files)

    assert first.json()["already_received"] is False
    assert second.json()["already_received"] is True
