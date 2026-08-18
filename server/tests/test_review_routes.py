from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _make_card(session, subject_sigla="TGDC", titulo="Aula", frente="F", verso="V", status="aceito", due_date=None):
    from sqlalchemy import select

    from app.models import CardProposal, Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == subject_sigla))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 1))
    session.add(lesson)
    session.flush()

    card = CardProposal(
        lesson_id=lesson.id, deriv_key=f"card:{titulo}:{frente}", frente=frente, verso=verso,
        start_s=0.0, end_s=5.0, status=status, due_date=due_date or date(2026, 3, 1),
    )
    session.add(card)
    session.commit()
    return card.id


def test_home_shows_review_count(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_card(session)

    response = client.get("/")
    assert "1" in response.text
    assert "/revisao" in response.text


def test_fila_json_lists_due_cards(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_card(session, frente="Pergunta")

    response = client.get("/revisao/fila.json")
    assert response.status_code == 200
    data = response.json()
    assert data["in_recovery"] is False
    assert len(data["cards"]) == 1
    assert data["cards"][0]["frente"] == "Pergunta"


def test_responder_json_updates_card_and_returns_result(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import CardProposal

    with holder.SessionLocal() as session:
        card_id = _make_card(session)

    response = client.post(
        f"/revisao/{card_id}/responder.json", data={"confianca": "tenho_certeza", "shortcut": "3"}
    )
    assert response.status_code == 200
    assert response.json()["acertou"] is True

    with holder.SessionLocal() as session:
        card = session.get(CardProposal, card_id)
        assert card.repetitions == 1


def test_responder_html_shows_feedback_and_listen_button_on_miss(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        card_id = _make_card(session)

    response = client.post(f"/revisao/{card_id}/responder", data={"confianca": "chutei", "shortcut": "1"})
    assert response.status_code == 200
    assert "errou" in response.text
    assert "ouvir os 30s de origem" in response.text


def test_pending_cards_are_not_in_the_queue(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_card(session, status="pendente")

    response = client.get("/revisao/fila.json")
    assert response.json()["cards"] == []


def test_calibration_page_renders(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        card_id = _make_card(session)

    client.post(f"/revisao/{card_id}/responder.json", data={"confianca": "chutei", "shortcut": "1"})

    response = client.get("/revisao/calibracao")
    assert response.status_code == 200
    assert "chutei" in response.text


def test_exam_mode_lists_cards_for_subject(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        _make_card(session, frente="Card de prova")
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

    response = client.get(f"/revisao/prova/{subject_id}")
    assert response.status_code == 200
    assert "Card de prova" in response.text


def test_exam_mode_404_for_unknown_subject(app_env):
    client = _authed_client()
    response = client.get("/revisao/prova/999999")
    assert response.status_code == 404
