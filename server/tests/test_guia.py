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
    não existe mais um `colar-guia` separado. A IA escreve `guia_md` como
    markdown corrido (título/sumário/seções, ver ai/bridge.py); o app deriva
    GuiaSecao/GuiaTopico/árvore em código a partir dele (ai/guia_parser.py)."""
    if secoes is None:
        secoes = [{"titulo": titulo, "corpo": "Conteúdo do guia."}]
    if topicos is None:
        topicos = [{"titulo": s["titulo"]} for s in secoes]

    parts = [f"# {titulo}\n"]
    if topicos:
        parts.append("## Sumário dos tópicos abordados\n")
        parts.append("\n".join(f"- {t['titulo']}" for t in topicos) + "\n")
    for s in secoes:
        parts.append(f"## {s['titulo']}\n")
        parts.append(s["corpo"] + "\n")
    guia_md = "\n".join(parts)

    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "destaque-prova", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 5.0}],
        "guia_md": guia_md,
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


def test_view_guia_shows_section_number_in_heading(app_env):
    """Achado real: o número já era calculado (usado na âncora e no
    sumário via <ol>), mas nunca aparecia impresso no <h2> da seção --
    quem lê o guia não via numeração nenhuma acompanhando o título."""
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    secoes = [
        {"titulo": "Introdução", "corpo": "Texto 1."},
        {"titulo": "Posse", "corpo": "Texto 2."},
    ]
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes)},
    )

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert "1. Introdução" in response.text
    assert "2. Posse" in response.text

    md_response = client.get(f"/lessons/{lesson_id}/guia.md")
    assert "## 1. Introdução" in md_response.text
    assert "## 2. Posse" in md_response.text


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


def test_view_guia_shows_generating_state_while_tts_job_pending(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=[{"titulo": "Posse", "corpo": "Conteúdo."}])},
    )

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert "narração sendo gerada" in response.text
    assert 'id="guia-player"' not in response.text


def test_tts_result_saves_section_audios_and_marks_lesson_ready(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson, TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={
            "resposta": _pasted_response(
                titulo="Aula",
                secoes=[
                    {"titulo": "Introdução", "corpo": "Texto 1."},
                    {"titulo": "Posse", "corpo": "Texto 2."},
                ],
                topicos=[{"titulo": "Introdução"}, {"titulo": "Posse"}],
            )
        },
    )

    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_guia"}).json()["job"]
    assert claim is not None
    assert claim["lesson_id"] == lesson_id
    assert [s["titulo"] for s in claim["guia_secoes"]] == ["Introdução", "Posse"]

    timestamps = json.dumps(
        [{"ordem": 0, "start_s": 0.0, "end_s": 3.0}, {"ordem": 1, "start_s": 3.6, "end_s": 7.0}]
    )
    response = client.post(
        f"/api/jobs/{claim['id']}/tts-result",
        data={"claim_token": claim["claim_token"], "timestamps": timestamps},
        files={"audio": ("guia.mp3", b"audio da aula inteira")},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "already_received": False}

    with holder.SessionLocal() as session:
        from app.models import GuiaSecao

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_audio_gerado_em is not None
        job = session.get(TranscriptionJob, claim["id"])
        assert job.status == "done"

        secoes = session.query(GuiaSecao).filter_by(lesson_id=lesson_id).order_by(GuiaSecao.ordem).all()
        assert secoes[0].audio_start_s == 0.0 and secoes[0].audio_end_s == 3.0
        assert secoes[1].audio_start_s == 3.6 and secoes[1].audio_end_s == 7.0

    from app import config

    lesson_dir = config.GUIA_AUDIO_DIR / f"lesson-{lesson_id}"
    assert (lesson_dir / "guia.mp3").read_bytes() == b"audio da aula inteira"

    # Reenvio idempotente (mesmo claim_token, job já "done") não duplica nem falha.
    again = client.post(
        f"/api/jobs/{claim['id']}/tts-result",
        data={"claim_token": claim["claim_token"], "timestamps": timestamps},
        files={"audio": ("guia.mp3", b"audio da aula inteira")},
    )
    assert again.json() == {"ok": True, "already_received": True}


def test_view_guia_shows_player_once_audio_ready(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=[{"titulo": "Posse", "corpo": "Conteúdo."}])},
    )
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_guia"}).json()["job"]
    client.post(
        f"/api/jobs/{claim['id']}/tts-result",
        data={"claim_token": claim["claim_token"], "timestamps": json.dumps([{"ordem": 0, "start_s": 0.0, "end_s": 3.0}])},
        files={"audio": ("guia.mp3", b"audio")},
    )

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert 'id="guia-player"' in response.text
    assert "narração sendo gerada" not in response.text
    assert f"/lessons/{lesson_id}/guia/audio.mp3" in response.text
    assert 'data-audio-start="0.0"' in response.text

    audio_response = client.get(f"/lessons/{lesson_id}/guia/audio.mp3")
    assert audio_response.status_code == 200
    assert audio_response.content == b"audio"


def test_renarrar_requeues_tts_job_without_touching_guia_content(app_env):
    """Botão "gerar narração de novo": recoloca só o job tts_guia na fila --
    pra quando a lógica de narração muda (limpeza de Markdown, voz) sem que o
    conteúdo do guia precise mudar junto, sem reprocessar a aula inteira com IA."""
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson, TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    secoes = [{"titulo": "Posse", "corpo": "Conteúdo."}]
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes)},
    )
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_guia"}).json()["job"]
    client.post(
        f"/api/jobs/{claim['id']}/tts-result",
        data={"claim_token": claim["claim_token"], "timestamps": json.dumps([{"ordem": 0, "start_s": 0.0, "end_s": 3.0}])},
        files={"audio": ("guia.mp3", b"audio")},
    )
    with holder.SessionLocal() as session:
        guia_md_antes = session.get(Lesson, lesson_id).guia_md

    response = client.post(f"/lessons/{lesson_id}/guia/renarrar", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/lessons/{lesson_id}/guia"

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_md == guia_md_antes  # conteúdo do guia intocado

        jobs = session.query(TranscriptionJob).filter_by(lesson_id=lesson_id, target="tts_guia").all()
    assert len(jobs) == 2
    assert {j.status for j in jobs} == {"done", "pending"}

    # idempotente -- clicar de novo com o job ainda pendente não duplica
    client.post(f"/lessons/{lesson_id}/guia/renarrar")
    with holder.SessionLocal() as session:
        jobs = session.query(TranscriptionJob).filter_by(lesson_id=lesson_id, target="tts_guia").all()
    assert len(jobs) == 2


def test_renarrar_404_before_guia_generated(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    assert client.post(f"/lessons/{lesson_id}/guia/renarrar").status_code == 404


def test_reprocessing_makes_existing_audio_stale_and_requeues(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    secoes = [{"titulo": "Posse", "corpo": "Conteúdo."}]
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes)},
    )
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_guia"}).json()["job"]
    client.post(
        f"/api/jobs/{claim['id']}/tts-result",
        data={"claim_token": claim["claim_token"], "timestamps": json.dumps([{"ordem": 0, "start_s": 0.0, "end_s": 3.0}])},
        files={"audio": ("guia.mp3", b"audio")},
    )
    assert 'id="guia-player"' in client.get(f"/lessons/{lesson_id}/guia").text

    # Reprocessa -- áudio antigo fica desatualizado, novo job entra sozinho.
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response(titulo="Aula", secoes=secoes)},
    )

    response = client.get(f"/lessons/{lesson_id}/guia")
    assert "narração sendo gerada" in response.text
    assert 'id="guia-player"' not in response.text

    with holder.SessionLocal() as session:
        jobs = session.query(TranscriptionJob).filter_by(lesson_id=lesson_id, target="tts_guia").all()
    assert len(jobs) == 2
    assert {j.status for j in jobs} == {"done", "pending"}
    assert client.post(f"/lessons/{lesson_id}/colar-guia", data={"resposta": "# x"}).status_code == 404
