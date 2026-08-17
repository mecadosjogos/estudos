from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def test_seed_sets_subject_colors(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        tgdc = session.scalar(select(Subject).where(Subject.sigla == "TGDC"))

    assert tgdc.cor == "#2563eb"


def test_create_lesson_for_civil_today(app_env):
    import datetime

    client = _authed_client()
    subjects_page = client.get("/subjects")
    assert "TGDC" in subjects_page.text

    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        tgdc_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

    today = datetime.date.today().isoformat()
    response = client.post(
        f"/subjects/{tgdc_id}/lessons",
        data={"titulo": "Aula de hoje", "data": today, "google_doc_url": ""},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Aula de hoje" in response.text
    assert "sem áudio" in response.text


def test_encerrar_and_reabrir_subject(app_env):
    client = _authed_client()

    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        cpol_id = session.scalar(select(Subject.id).where(Subject.sigla == "CPOL"))

    client.post(f"/subjects/{cpol_id}/encerrar", follow_redirects=True)
    with holder.SessionLocal() as session:
        assert session.get(Subject, cpol_id).encerrada_em is not None

    client.post(f"/subjects/{cpol_id}/reabrir", follow_redirects=True)
    with holder.SessionLocal() as session:
        assert session.get(Subject, cpol_id).encerrada_em is None


def test_new_subject_can_continue_previous_one(app_env):
    client = _authed_client()

    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        tgdc_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

    client.post(
        "/subjects",
        data={
            "nome": "Direito Civil II",
            "sigla": "CIV2",
            "cor": "#111111",
            "diploma_padrao": "CC",
            "continua_de_id": str(tgdc_id),
        },
        follow_redirects=True,
    )

    with holder.SessionLocal() as session:
        civ2 = session.scalar(select(Subject).where(Subject.sigla == "CIV2"))
        assert civ2.continua_de_id == tgdc_id


def test_move_lesson_between_subjects(app_env):
    client = _authed_client()

    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        tgdc_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        tgc_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGC"))

    client.post(
        f"/subjects/{tgdc_id}/lessons",
        data={"titulo": "Aula trocada", "data": "2026-03-12", "google_doc_url": ""},
    )
    with holder.SessionLocal() as session:
        lesson_id = session.scalar(select(Lesson.id).where(Lesson.titulo == "Aula trocada"))

    response = client.post(
        f"/lessons/{lesson_id}/move", data={"subject_id": tgc_id}, follow_redirects=True
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        assert session.get(Lesson, lesson_id).subject_id == tgc_id
