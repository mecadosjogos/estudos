import io
import json

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client, app


def _create_term_with_definition(client, termo="Posse", definicao="Exercício de fato de poderes de propriedade."):
    client.post("/termos/criar", data={"termo": termo, "definicao_md": definicao, "citacao_literal": ""})
    from sqlalchemy import select

    from app.db import holder
    from app.assuntos import normalize_slug
    from app.models import Term

    with holder.SessionLocal() as session:
        return session.scalar(select(Term.id).where(Term.slug == normalize_slug(termo)))


def _override_asr(app, text="a posse é o exercício de fato"):
    from app.media.asr import FakeASRClient, TranscriptionResult, get_asr_client

    app.dependency_overrides[get_asr_client] = lambda: FakeASRClient(TranscriptionResult(text=text, words=[]))


def _pasted_feynman_response(overrides=None):
    payload = {
        "pontos_cobertos": ["exercício de fato"],
        "pontos_faltantes": ["poderes de propriedade"],
        "divergencias_terminologicas": [],
        "comentario_geral": "Bom começo, falta detalhar.",
    }
    if overrides:
        payload.update(overrides)
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_upload_transcribes_synchronously_via_fake_asr(app_env):
    client, app = _authed_client()
    term_id = _create_term_with_definition(client)
    _override_asr(app, text="posse é o exercício de fato de poderes")

    response = client.post(
        f"/termos/{term_id}/feynman",
        files={"audio": ("gravacao.webm", io.BytesIO(b"fake-audio-bytes"), "audio/webm")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "posse é o exercício de fato de poderes" in response.text

    from sqlalchemy import select

    from app.db import holder
    from app.models import FeynmanAttempt

    with holder.SessionLocal() as session:
        attempt = session.scalar(select(FeynmanAttempt).where(FeynmanAttempt.term_id == term_id))
        assert attempt.status == "transcrito"
        assert attempt.transcript_text == "posse é o exercício de fato de poderes"


def test_evaluate_automatically_without_api_key_shows_error(app_env):
    client, app = _authed_client()
    term_id = _create_term_with_definition(client)
    _override_asr(app)
    client.post(
        f"/termos/{term_id}/feynman",
        files={"audio": ("g.webm", io.BytesIO(b"x"), "audio/webm")},
    )

    from sqlalchemy import select

    from app.db import holder
    from app.models import FeynmanAttempt

    with holder.SessionLocal() as session:
        attempt_id = session.scalar(select(FeynmanAttempt.id).where(FeynmanAttempt.term_id == term_id))

    response = client.post(f"/termos/{term_id}/feynman/{attempt_id}/avaliar", follow_redirects=True)
    assert response.status_code == 200
    assert "erro_ia" in str(response.url)


def test_colar_resposta_completes_feynman_evaluation(app_env):
    client, app = _authed_client()
    term_id = _create_term_with_definition(client)
    _override_asr(app)
    client.post(
        f"/termos/{term_id}/feynman",
        files={"audio": ("g.webm", io.BytesIO(b"x"), "audio/webm")},
    )

    from sqlalchemy import select

    from app.db import holder
    from app.models import FeynmanAttempt

    with holder.SessionLocal() as session:
        attempt_id = session.scalar(select(FeynmanAttempt.id).where(FeynmanAttempt.term_id == term_id))

    response = client.post(
        f"/termos/{term_id}/feynman/{attempt_id}/colar-resposta",
        data={"resposta": _pasted_feynman_response()},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "exercício de fato" in response.text
    assert "poderes de propriedade" in response.text
    assert "Bom começo" in response.text

    with holder.SessionLocal() as session:
        attempt = session.get(FeynmanAttempt, attempt_id)
        assert attempt.status == "avaliado"
        assert attempt.ai_call_id is not None


def test_colar_resposta_invalida_mostra_erro_sem_gravar(app_env):
    client, app = _authed_client()
    term_id = _create_term_with_definition(client)
    _override_asr(app)
    client.post(
        f"/termos/{term_id}/feynman",
        files={"audio": ("g.webm", io.BytesIO(b"x"), "audio/webm")},
    )

    from sqlalchemy import select

    from app.db import holder
    from app.models import FeynmanAttempt

    with holder.SessionLocal() as session:
        attempt_id = session.scalar(select(FeynmanAttempt.id).where(FeynmanAttempt.term_id == term_id))

    response = client.post(
        f"/termos/{term_id}/feynman/{attempt_id}/colar-resposta",
        data={"resposta": "isso não é json"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "erro" in str(response.url)

    with holder.SessionLocal() as session:
        assert session.get(FeynmanAttempt, attempt_id).status == "transcrito"


def test_download_prompt_includes_definition_and_transcript(app_env):
    client, app = _authed_client()
    term_id = _create_term_with_definition(client, definicao="Def. de posse pra teste de prompt.")
    _override_asr(app, text="minha explicacao falada")
    client.post(
        f"/termos/{term_id}/feynman",
        files={"audio": ("g.webm", io.BytesIO(b"x"), "audio/webm")},
    )

    from sqlalchemy import select

    from app.db import holder
    from app.models import FeynmanAttempt

    with holder.SessionLocal() as session:
        attempt_id = session.scalar(select(FeynmanAttempt.id).where(FeynmanAttempt.term_id == term_id))

    response = client.get(f"/termos/{term_id}/feynman/{attempt_id}/prompt.md")
    assert response.status_code == 200
    assert "Def. de posse pra teste de prompt." in response.text
    assert "minha explicacao falada" in response.text
    assert "Content-Disposition" in response.headers


def test_feynman_entry_point_on_term_page(app_env):
    client, app = _authed_client()
    term_id = _create_term_with_definition(client)
    response = client.get(f"/termos/{term_id}")
    assert f"/termos/{term_id}/feynman" in response.text
