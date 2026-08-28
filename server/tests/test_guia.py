import json
from datetime import date, datetime, timezone

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _make_transcribed_lesson(session, texts, titulo="Aula com transcrição"):
    from sqlalchemy import select

    from app.models import AudioSegment, Lesson, Subject, Transcript

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    session.add(AudioSegment(
        lesson_id=lesson.id, ordem=1, original_filename="aula.m4a",
        storage_path="/tmp/x", size_bytes=10, status="complete",
    ))

    transcript = Transcript(
        lesson_id=lesson.id, engine="e", worker_name="w",
        full_text=" ".join(texts), duration_s=float(len(texts) * 10),
    )
    session.add(transcript)
    session.commit()
    return lesson.id


def _pasted_response(titulo="Aula sem título identificado", secoes=None, topicos=None) -> str:
    """O guia sai da MESMA resposta que a aula editada (fase 6 revisada) --
    não existe mais um `colar-guia` separado. Ver ai/schemas.py, guia_titulo
    e demais campos guia_*."""
    if secoes is None:
        secoes = [{"titulo": titulo, "corpo": "Conteúdo do guia."}]
    if topicos is None:
        topicos = [{"titulo": s["titulo"]} for s in secoes]
    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 5.0}],
        "guia_titulo": titulo,
        "guia_arvore": [],
        "guia_secoes": secoes,
        "guia_topicos": topicos,
        "guia_trechos_incompletos": [],
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def test_colar_resposta_saves_guia_alongside_aula_editada(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    resposta = _pasted_response(
        titulo="Aula sem título identificado",
        secoes=[{"titulo": "Aula sem título identificado", "corpo": "> A posse exige **corpus** e **animus**."}],
    )
    response = client.post(
        f"/lessons/{lesson_id}/colar-resposta", data={"resposta": resposta}, follow_redirects=True
    )
    assert response.status_code == 200
    assert response.url.path == f"/lessons/{lesson_id}/aula-editada"

    with holder.SessionLocal() as session:
        from app.models import GuiaSecao, GuiaTopico, Lesson

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_md.startswith("# Aula sem título identificado")
        assert lesson.guia_gerado_em is not None
        assert lesson.guia_titulo == "Aula sem título identificado"
        assert lesson.resumo == "Resumo curto."  # aula editada veio junto, mesma chamada
        assert session.query(GuiaSecao).filter_by(lesson_id=lesson_id).count() == 1
        assert session.query(GuiaTopico).filter_by(lesson_id=lesson_id).count() == 1


def test_view_guia_renders_structured_page(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    resposta = _pasted_response(
        titulo="Aula sem título identificado",
        secoes=[{"titulo": "Posse", "corpo": "> A posse exige **corpus** e **animus**."}],
    )
    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": resposta})

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert response.status_code == 200
    # Markdown da seção convertido em HTML de verdade.
    assert "<strong>corpus</strong>" in response.text
    assert "<blockquote>" in response.text
    # Página estruturada nova: sumário navegável e âncora de seção, não o
    # blob único do guia_legado.html.
    assert 'class="guia-sumario"' in response.text
    assert 'id="secao-1"' in response.text


def test_view_guia_falls_back_to_legado_without_guia_secao(app_env):
    """Aula processada antes da estruturação do guia (guia_md preenchido,
    mas sem GuiaSecao) continua mostrando o guia do jeito que sempre foi --
    nenhuma migração/backfill é necessária."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        from app.models import Lesson

        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])
        lesson = session.get(Lesson, lesson_id)
        lesson.guia_md = "# Guia antigo\n\n> Conteúdo **antigo**."
        lesson.guia_gerado_em = datetime.now(timezone.utc)
        session.commit()

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert response.status_code == 200
    assert "<strong>antigo</strong>" in response.text
    assert 'class="guia-sumario"' not in response.text


def test_view_guia_404_before_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert response.status_code == 404


def test_download_guia_md_returns_raw_markdown(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Guia", secoes=[{"titulo": "Guia", "corpo": "conteúdo real"}])},
    )

    response = client.get(f"/lessons/{lesson_id}/guia.md")
    assert response.status_code == 200
    # Não é mais passthrough de string crua da IA -- é remontado a partir
    # dos campos estruturados, então checamos o conteúdo esperado presente,
    # não igualdade byte-a-byte.
    assert response.text.startswith("# Guia")
    assert "conteúdo real" in response.text
    assert "Content-Disposition" in response.headers


def test_guia_topico_secao_alvo_correction_survives_reprocessing(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    secoes = [
        {"titulo": "Introdução", "corpo": "Texto da introdução."},
        {"titulo": "Posse", "corpo": "Texto sobre posse."},
    ]
    topicos = [{"titulo": "Introdução"}, {"titulo": "Posse"}]
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes, topicos=topicos)},
    )

    with holder.SessionLocal() as session:
        from app.models import GuiaTopico

        topico = session.query(GuiaTopico).filter_by(lesson_id=lesson_id, titulo="Introdução").one()
        topico_id = topico.id
        assert topico.secao_alvo_slug is None

    # Corrige manualmente "Introdução" pra apontar pra seção 2 ("Posse").
    response = client.post(
        f"/lessons/{lesson_id}/guia/topicos/{topico_id}/secao-alvo",
        data={"secao_ordem": 2},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with holder.SessionLocal() as session:
        from app.models import GuiaTopico

        topico = session.get(GuiaTopico, topico_id)
        assert topico.secao_alvo_slug == "posse"
        assert topico.editado_em is not None

    # Reprocessa a aula -- a correção precisa sobreviver.
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes, topicos=topicos)},
    )
    with holder.SessionLocal() as session:
        from app.models import GuiaTopico

        topico = session.get(GuiaTopico, topico_id)
        assert topico.secao_alvo_slug == "posse"


def test_guia_topico_secao_alvo_shows_warning_when_target_disappears(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    secoes = [
        {"titulo": "Introdução", "corpo": "Texto da introdução."},
        {"titulo": "Posse", "corpo": "Texto sobre posse."},
    ]
    topicos = [{"titulo": "Introdução"}, {"titulo": "Posse"}]
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes, topicos=topicos)},
    )

    with holder.SessionLocal() as session:
        from app.models import GuiaTopico

        topico_id = session.query(GuiaTopico).filter_by(lesson_id=lesson_id, titulo="Introdução").one().id

    client.post(f"/lessons/{lesson_id}/guia/topicos/{topico_id}/secao-alvo", data={"secao_ordem": 2})

    # Reprocessa com uma estrutura diferente -- a seção "Posse" não existe
    # mais, então a correção salva (pelo slug "posse") não encontra alvo.
    novas_secoes = [
        {"titulo": "Introdução", "corpo": "Texto novo."},
        {"titulo": "Responsabilidade civil", "corpo": "Texto novo 2."},
    ]
    novos_topicos = [{"titulo": "Introdução"}, {"titulo": "Responsabilidade civil"}]
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=novas_secoes, topicos=novos_topicos)},
    )

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert response.status_code == 200
    assert "seção-alvo desatualizada" in response.text


def test_lesson_detail_shows_view_guia_button_after_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Guia", secoes=[{"titulo": "Guia", "corpo": "conteúdo"}])},
    )

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/guia\"" in response.text


def test_lesson_detail_hides_guia_button_before_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    response = client.get(f"/lessons/{lesson_id}")
    assert f"/lessons/{lesson_id}/guia\"" not in response.text


def test_guia_pacote_and_colar_guia_routes_no_longer_exist(app_env):
    """Rotas removidas na fase 6 revisada -- guia sai do mesmo
    pacote.md/colar-resposta da aula editada (ver ai/schemas.py)."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["texto qualquer"])

    assert client.get(f"/lessons/{lesson_id}/guia-pacote.md").status_code == 404
    assert client.get(f"/lessons/{lesson_id}/colar-guia").status_code == 404
    assert client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": "# x"}).status_code == 404
