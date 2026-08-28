import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _lesson_with_transcript_id(session, subject_sigla="TGDC", titulo="Aula assuntos") -> int:
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == subject_sigla))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
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


def _pasted_response(assuntos) -> str:
    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "conceito", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 5.0}],
        "guia_titulo": "Posse", "guia_secoes": [{"titulo": "Posse", "corpo": "Guia de teste."}],
        "guia_topicos": [{"titulo": "Posse"}],
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": assuntos,
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_processar_manual_creates_pending_assunto_proposal(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(
        f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Posse", "Capacidade"])}
    )

    response = client.get(f"/lessons/{lesson_id}/aprovacao")
    assert "Posse" in response.text
    assert "Capacidade" in response.text


def test_accept_lesson_assunto_creates_assunto_and_cobertura(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Assunto, AssuntoCobertura, LessonAssunto

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Posse"])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))

    response = client.post(
        f"/lessons/{lesson_id}/assuntos/{proposal_id}/aceitar", data={"titulo": "Posse"}, follow_redirects=True
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        assunto = session.scalar(select(Assunto).where(Assunto.slug == "posse"))
        assert assunto is not None
        proposal = session.get(LessonAssunto, proposal_id)
        assert proposal.status == "aceito"
        assert proposal.assunto_id == assunto.id
        cobertura = session.scalar(
            select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == assunto.id)
        )
        assert cobertura is not None


def test_approval_screen_suggests_merge_for_similar_assunto(app_env):
    client = _authed_client()
    from app.assuntos import find_or_create_assunto
    from app.db import holder

    with holder.SessionLocal() as session:
        find_or_create_assunto(session, "Capacidade de Fato")
        session.commit()
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Capacidade"])})

    response = client.get(f"/lessons/{lesson_id}/aprovacao")
    assert "juntar em" in response.text
    assert "Capacidade de Fato" in response.text


def test_accepting_existing_spelling_does_not_create_second_assunto(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.assuntos import find_or_create_assunto
    from app.db import holder
    from app.models import Assunto, LessonAssunto

    with holder.SessionLocal() as session:
        find_or_create_assunto(session, "Capacidade de Fato")
        session.commit()
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Capacidade"])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/assuntos/{proposal_id}/aceitar", data={"titulo": "Capacidade de Fato"})

    with holder.SessionLocal() as session:
        assuntos = session.scalars(select(Assunto)).all()
        assert len(assuntos) == 1


def test_accept_two_lessons_same_topic_dedupe_into_one_assunto(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Assunto, LessonAssunto

    with holder.SessionLocal() as session:
        lesson1 = _lesson_with_transcript_id(session, titulo="Aula 1")
        lesson2 = _lesson_with_transcript_id(session, titulo="Aula 2")

    client.post(f"/lessons/{lesson1}/colar-resposta", data={"resposta": _pasted_response(["Usucapião"])})
    client.post(f"/lessons/{lesson2}/colar-resposta", data={"resposta": _pasted_response(["usucapiao"])})

    with holder.SessionLocal() as session:
        p1 = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson1))
        p2 = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson2))

    client.post(f"/lessons/{lesson1}/assuntos/{p1}/aceitar", data={"titulo": "Usucapião"})
    client.post(f"/lessons/{lesson2}/assuntos/{p2}/aceitar", data={"titulo": "usucapiao"})

    with holder.SessionLocal() as session:
        assuntos = session.scalars(select(Assunto)).all()
        assert len(assuntos) == 1


def test_assunto_detail_page_shows_linked_lessons_and_cards(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import CardProposal, LessonAssunto

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Posse"])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))
        card = CardProposal(
            lesson_id=lesson_id, deriv_key="card:x", frente="F", verso="V",
            start_s=0.0, end_s=1.0, status="aceito",
        )
        session.add(card)
        session.commit()

    client.post(f"/lessons/{lesson_id}/assuntos/{proposal_id}/aceitar", data={"titulo": "Posse"})

    with holder.SessionLocal() as session:
        from app.models import Assunto
        assunto_id = session.scalar(select(Assunto.id).where(Assunto.slug == "posse"))

    response = client.get(f"/assuntos/{assunto_id}")
    assert response.status_code == 200
    assert "Aula assuntos" in response.text
    assert "1 card(s) ativo(s)" in response.text


def test_assunto_detail_page_shows_termos_artigos_e_material(app_env):
    """Fase 12: "une informações antigas" — termos aceitos, artigos
    citados e material usado nas aulas vinculadas ao assunto, sem tabela
    de vínculo nova (derivado de lesson_id)."""
    import json as jsonlib

    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Assunto, Definition, LessonAssunto, Material, MaterialUse, Subject

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        material = Material(titulo="Resumo de posse", origem="texto", conteudo_md="x", status="ok")
        session.add(material)
        session.flush()
        session.add(MaterialUse(material_id=material.id, subject_id=subject_id, lesson_id=lesson_id, rotulo="cap. 3"))
        session.commit()

    payload = {
        "resumo": "R.",
        "aula_editada": [{"tipo": "conceito", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0}],
        "indice": [], "guia_titulo": "G", "guia_secoes": [], "guia_topicos": [],
        "artigos": [{"texto_citado": "art. 1.196 CC", "start_s": 0.0}],
        "datas_anunciadas": [], "cards": [],
        "termos": [{"termo": "Posse", "definicao": "Def.", "citacao_literal": "cit.", "start_s": 0.0, "variantes": []}],
        "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": ["Posse"],
    }
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": "```json\n" + jsonlib.dumps(payload, ensure_ascii=False) + "\n```"},
    )

    with holder.SessionLocal() as session:
        assunto_proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))
        termo_proposal_id = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/assuntos/{assunto_proposal_id}/aceitar", data={"titulo": "Posse"})
    client.post(f"/lessons/{lesson_id}/termos/{termo_proposal_id}/aceitar", data={"termo": "Posse"})

    with holder.SessionLocal() as session:
        assunto_id = session.scalar(select(Assunto.id).where(Assunto.slug == "posse"))

    response = client.get(f"/assuntos/{assunto_id}")
    assert response.status_code == 200
    assert "Posse" in response.text  # termo relacionado
    assert "art. 1.196 CC" in response.text
    assert "Resumo de posse" in response.text
    assert "cap. 3" in response.text


def test_fundir_migrates_links_and_redirects_to_target(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Assunto, LessonAssunto

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Capacidade de Fato"])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/assuntos/{proposal_id}/aceitar", data={"titulo": "Capacidade de Fato"})

    with holder.SessionLocal() as session:
        from app.assuntos import find_or_create_assunto

        source = session.scalar(select(Assunto).where(Assunto.slug == "capacidade-de-fato"))
        target = find_or_create_assunto(session, "Capacidade")
        session.commit()
        source_id, target_id = source.id, target.id

    response = client.post(
        f"/assuntos/{source_id}/fundir", data={"target_id": target_id}, follow_redirects=True
    )
    assert response.status_code == 200
    assert response.url.path == f"/assuntos/{target_id}"

    with holder.SessionLocal() as session:
        assert session.get(Assunto, source_id) is None
        link = session.scalar(select(LessonAssunto).where(LessonAssunto.lesson_id == lesson_id))
        assert link.assunto_id == target_id


def test_assuntos_list_page_and_search(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import LessonAssunto

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Usucapião"])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/assuntos/{proposal_id}/aceitar", data={"titulo": "Usucapião"})

    response = client.get("/assuntos")
    assert "Usucapião" in response.text

    hit = client.get("/assuntos?q=usucap")
    assert "Usucapião" in hit.text

    miss = client.get("/assuntos?q=inexistente")
    assert "Usucapião" not in miss.text


def test_separar_moves_link_to_new_assunto(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Assunto, LessonAssunto

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response(["Capacidade"])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(LessonAssunto.id).where(LessonAssunto.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/assuntos/{proposal_id}/aceitar", data={"titulo": "Capacidade"})

    with holder.SessionLocal() as session:
        original = session.scalar(select(Assunto).where(Assunto.slug == "capacidade"))
        link = session.scalar(select(LessonAssunto).where(LessonAssunto.lesson_id == lesson_id))
        original_id, link_id = original.id, link.id

    response = client.post(
        f"/assuntos/{original_id}/vinculos/{link_id}/separar",
        data={"novo_titulo": "Capacidade de Fato"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        link = session.get(LessonAssunto, link_id)
        novo = session.scalar(select(Assunto).where(Assunto.slug == "capacidade-de-fato"))
        assert link.assunto_id == novo.id
