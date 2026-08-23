from datetime import date, timedelta

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _subject_id(session, sigla="TGDC"):
    from sqlalchemy import select

    from app.models import Subject

    return session.scalar(select(Subject.id).where(Subject.sigla == sigla))


def test_post_ementa_creates_topics_and_shows_on_subject_page(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)

    response = client.post(
        f"/subjects/{subject_id}/ementa",
        data={"topicos": "Pessoa natural\nCapacidade\nDomicílio"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Pessoa natural" in response.text
    assert "Capacidade" in response.text
    assert "Domicílio" in response.text


def test_create_exam_with_scope_and_view_panel(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.assuntos import ensure_cobertura, find_or_create_assunto
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Posse")
        ensure_cobertura(session, assunto.id, subject_id)
        session.commit()
        assunto_id = assunto.id

    data_prova = (date.today() + timedelta(days=9)).isoformat()
    response = client.post(
        f"/subjects/{subject_id}/exams",
        data={"titulo": "P1", "data": data_prova, "assunto_ids": [str(assunto_id)]},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "P1" in response.text
    assert "Posse" in response.text
    assert "dia(s) restante(s)" in response.text


def test_subject_page_lists_created_exam(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)

    client.post(
        f"/subjects/{subject_id}/exams",
        data={"titulo": "Final", "data": (date.today() + timedelta(days=30)).isoformat()},
    )

    response = client.get(f"/subjects/{subject_id}")
    assert "Final" in response.text


def test_add_and_remove_assunto_from_scope(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.assuntos import find_or_create_assunto
    from app.db import holder
    from app.models import Exam

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Prescrição")
        session.commit()
        assunto_id = assunto.id

    client.post(
        f"/subjects/{subject_id}/exams",
        data={"titulo": "P2", "data": (date.today() + timedelta(days=5)).isoformat()},
    )
    with holder.SessionLocal() as session:
        exam_id = session.scalar(select(Exam.id).where(Exam.titulo == "P2"))

    response = client.post(f"/exams/{exam_id}/escopo", data={"assunto_id": assunto_id}, follow_redirects=True)
    assert "Prescrição" in response.text

    response = client.post(f"/exams/{exam_id}/escopo/{assunto_id}/remover", follow_redirects=True)
    assert "Nenhum assunto no escopo ainda." in response.text


def test_download_apanhado_pdf(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.assuntos import ensure_cobertura, find_or_create_assunto
    from app.db import holder
    from app.models import Exam

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Posse")
        ensure_cobertura(session, assunto.id, subject_id)
        session.commit()
        assunto_id = assunto.id

    client.post(
        f"/subjects/{subject_id}/exams",
        data={"titulo": "P1", "data": (date.today() + timedelta(days=9)).isoformat(), "assunto_ids": [str(assunto_id)]},
    )
    with holder.SessionLocal() as session:
        exam_id = session.scalar(select(Exam.id).where(Exam.titulo == "P1"))

    response = client.get(f"/exams/{exam_id}/apanhado.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
