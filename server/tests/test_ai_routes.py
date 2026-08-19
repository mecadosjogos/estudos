import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _lesson_with_transcript_id(session) -> int:
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo="Aula rotas IA", data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    transcript = Transcript(
        lesson_id=lesson.id, engine="e", worker_name="w",
        full_text="a posse exige corpus e animus", duration_s=5.0,
    )
    session.add(transcript)
    session.flush()
    words = [{"text": w, "start_s": 0.0, "end_s": 5.0, "probability": 0.95} for w in "a posse exige corpus e animus".split()]
    session.add(TranscriptSegment(
        transcript_id=transcript.id, idx=0, start_s=0.0, end_s=5.0,
        text="a posse exige corpus e animus", words_json=json.dumps(words),
    ))
    session.commit()
    return lesson.id


def _pasted_response(overrides=None) -> str:
    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 5.0}],
        "artigos": [],
        "datas_anunciadas": [{"texto": "prova dia 12", "data_anunciada": "2026-04-12", "start_s": 1.0}],
        "cards": [{"frente": "Pergunta", "verso": "Resposta", "start_s": 0.0, "end_s": 5.0}],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    if overrides:
        payload.update(overrides)
    return "texto antes\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```\ntexto depois"


def test_processar_sem_api_key_mostra_erro_claro(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.post(f"/lessons/{lesson_id}/processar", follow_redirects=True)
    assert response.status_code == 200
    assert "erro_ia" in str(response.url)


def test_download_pacote_md_contains_transcript(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.get(f"/lessons/{lesson_id}/pacote.md")
    assert response.status_code == 200
    assert "posse exige corpus" in response.text
    assert "Content-Disposition" in response.headers


def test_download_pacote_sem_transcricao_da_erro_400(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem transcricao", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    response = client.get(f"/lessons/{lesson_id}/pacote.md")
    assert response.status_code == 400


def test_colar_resposta_completa_o_ciclo(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.post(
        f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()}, follow_redirects=True
    )
    assert response.status_code == 200
    assert response.url.path == f"/lessons/{lesson_id}/aula-editada"
    assert "A posse exige corpus e animus." in response.text
    assert "Resumo curto." in response.text


def test_colar_resposta_invalida_mostra_erro_sem_gravar(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.post(
        f"/lessons/{lesson_id}/colar-resposta", data={"resposta": "isso não é json"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "erro" in str(response.url)

    with holder.SessionLocal() as session:
        assert session.get(Lesson, lesson_id).resumo is None


def test_approval_screen_lists_pending_cards_and_announcements(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})
    response = client.get(f"/lessons/{lesson_id}/aprovacao")

    assert "Pergunta" in response.text
    assert "Resposta" in response.text
    assert "prova dia 12" in response.text


def test_accept_card_removes_it_from_pending_list(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import CardProposal

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    with holder.SessionLocal() as session:
        card_id = session.scalar(select(CardProposal.id).where(CardProposal.lesson_id == lesson_id))

    response = client.post(f"/lessons/{lesson_id}/cards/{card_id}/aceitar", follow_redirects=True)
    assert "Nenhum card pendente." in response.text

    with holder.SessionLocal() as session:
        assert session.get(CardProposal, card_id).status == "aceito"


def test_edit_card_marks_editado_em(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import CardProposal

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    with holder.SessionLocal() as session:
        card_id = session.scalar(select(CardProposal.id).where(CardProposal.lesson_id == lesson_id))

    client.post(
        f"/lessons/{lesson_id}/cards/{card_id}/editar",
        data={"frente": "Pergunta editada", "verso": "Resposta editada"},
    )

    with holder.SessionLocal() as session:
        card = session.get(CardProposal, card_id)
        assert card.frente == "Pergunta editada"
        assert card.status == "aceito"
        assert card.editado_em is not None


def test_discard_announcement(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import AnnouncementProposal

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response()})

    with holder.SessionLocal() as session:
        ann_id = session.scalar(select(AnnouncementProposal.id).where(AnnouncementProposal.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/announcements/{ann_id}/descartar")

    with holder.SessionLocal() as session:
        assert session.get(AnnouncementProposal, ann_id).status == "descartado"


def test_block_observacao_and_confirmacao(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import EditedBlock

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response({"artigos": [{"texto_citado": "art. 1 CC", "start_s": 0.0}]})},
    )

    with holder.SessionLocal() as session:
        block_id = session.scalar(select(EditedBlock.id).where(EditedBlock.lesson_id == lesson_id))

    response = client.post(
        f"/lessons/{lesson_id}/blocks/{block_id}/observacao",
        data={"observacao": "Minha nota"},
        follow_redirects=True,
    )
    assert "Minha nota" in response.text

    with holder.SessionLocal() as session:
        assert session.get(EditedBlock, block_id).observacao == "Minha nota"

    client.post(f"/lessons/{lesson_id}/blocks/{block_id}/confirmar")
    with holder.SessionLocal() as session:
        assert session.get(EditedBlock, block_id).confirmado_em is not None


def test_lesson_detail_shows_processing_buttons_disabled_when_transcribed(app_env):
    """Os botões de processamento de IA na tela da aula estão desligados
    temporariamente (decisão do usuário) — as rotas continuam existindo
    (o RUNBOOK/skill fala com elas direto por curl), só a UI não oferece
    o clique."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/processar" in response.text
    assert "disabled" in response.text
    assert f"/lessons/{lesson_id}/pacote.md" not in response.text
    assert f"/lessons/{lesson_id}/colar-resposta" not in response.text
