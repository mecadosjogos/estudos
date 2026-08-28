from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _make_transcribed_lesson(session, texts, titulo="Aula com transcrição"):
    from sqlalchemy import select

    from app.models import Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    transcript = Transcript(
        lesson_id=lesson.id,
        engine="faster-whisper-large-v3",
        worker_name="desktop-4070",
        full_text=" ".join(texts),
        duration_s=float(len(texts) * 10),
    )
    session.add(transcript)
    session.flush()

    for i, text in enumerate(texts):
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                idx=i,
                start_s=float(i * 10),
                end_s=float(i * 10 + 8),
                text=text,
                words_json="[]",
            )
        )
    session.commit()
    return lesson.id


def test_search_finds_matching_segment(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(
            session, ["o prazo da usucapião extraordinária é de quinze anos"]
        )

    response = client.get("/search", params={"q": "usucapião"})
    assert response.status_code == 200
    assert "Aula com transcrição" in response.text
    assert "<mark>" in response.text


def test_search_is_accent_insensitive(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, ["a usucapião extraordinária independe de justo título"])

    response = client.get("/search", params={"q": "usucapiao"})
    assert response.status_code == 200
    assert "Aula com transcrição" in response.text


def test_search_no_results(app_env):
    client = _authed_client()
    response = client.get("/search", params={"q": "termo-que-nao-existe-em-lugar-nenhum"})
    assert response.status_code == 200
    assert "Nada encontrado" in response.text


def test_search_link_points_to_the_right_timestamp(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(
            session, ["fato irrelevante", "aqui fala de negócio jurídico direto"]
        )

    response = client.get("/search", params={"q": "negócio"})
    assert f"/lessons/{lesson_id}/transcricao?t=10.0" in response.text


def test_search_tolerates_special_characters(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, ["o art. 1.238 do código civil trata da usucapião"])

    for query in ["art. 1.238", "usucapião-extraordinária", 'aspas"soltas', "* -- OR"]:
        response = client.get("/search", params={"q": query})
        assert response.status_code == 200, f"query {query!r} quebrou a busca"


def test_reprocessing_removes_old_segments_from_search_index(app_env):
    """Reindexar é apagar-e-regravar (Integridade #2 do PLANO.md) — a busca
    não pode continuar achando um texto que já foi substituído."""
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Transcript

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["conteúdo antigo e específico da primeira versão"])

    before = client.get("/search", params={"q": "específico"})
    assert "Aula com transcrição" in before.text

    with holder.SessionLocal() as session:
        old = session.scalar(select(Transcript).where(Transcript.lesson_id == lesson_id))
        session.delete(old)
        session.commit()

    after = client.get("/search", params={"q": "específico"})
    assert "Nada encontrado" in after.text


def test_lesson_transcript_page_renders_synced_segments(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["primeiro trecho", "segundo trecho"])

    response = client.get(f"/lessons/{lesson_id}/transcricao")
    assert response.status_code == 200
    assert 'data-start="0.0"' in response.text
    assert 'data-start="10.0"' in response.text
    assert "initReadingPage" in response.text


def test_download_transcript_txt_has_plain_text_no_timestamps(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["primeiro trecho", "segundo trecho"])

    response = client.get(f"/lessons/{lesson_id}/transcricao.txt")
    assert response.status_code == 200
    assert "primeiro trecho" in response.text
    assert "segundo trecho" in response.text
    assert "data-start" not in response.text
    assert "Content-Disposition" in response.headers
    assert f"transcricao-{lesson_id}.txt" in response.headers["Content-Disposition"]


def test_download_transcript_txt_404_without_transcript(app_env):
    client = _authed_client()
    from datetime import date

    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem transcrição", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    response = client.get(f"/lessons/{lesson_id}/transcricao.txt")
    assert response.status_code == 404


def test_lesson_audio_route_404_without_file(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["trecho qualquer"])

    response = client.get(f"/lessons/{lesson_id}/audio")
    assert response.status_code == 404


def test_lesson_audio_route_serves_file(app_env):
    from app import config

    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["trecho qualquer"])

    config.MEDIA_WEB_DIR.mkdir(parents=True, exist_ok=True)
    (config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3").write_bytes(b"fake-mp3-bytes")

    response = client.get(f"/lessons/{lesson_id}/audio")
    assert response.status_code == 200
    assert response.content == b"fake-mp3-bytes"


def test_search_finds_material_content(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import Subject

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

    client.post(
        "/materials",
        data={
            "titulo": "Resumo de posse",
            "origem": "texto",
            "texto": "posse exige corpus e animus segundo a doutrina majoritária",
            "subject_id": str(subject_id),
        },
    )

    response = client.get("/search", params={"q": "corpus"})
    assert response.status_code == 200
    assert "Resumo de posse" in response.text
    assert "Material" in response.text


def test_search_finds_material_page_content(app_env):
    import io

    import fitz

    client = _authed_client()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A posse exige corpus e animus de verdade nesta pagina.")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post("/works", data={"titulo": "Obra de busca"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "1"},
        files={"arquivo": ("c.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    response = client.get("/search", params={"q": "animus"})
    assert response.status_code == 200
    assert "Obra de busca" in response.text
    assert "Página de obra" in response.text


def test_search_finds_observacao_content(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import EditedBlock

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["a posse exige corpus e animus"])

    payload = {
        "resumo": "R.", "aula_editada": [
            {"tipo": "conceito", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0}
        ],
        "indice": [], "guia_titulo": "G", "guia_secoes": [], "guia_topicos": [],
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    import json as jsonlib
    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": "```json\n" + jsonlib.dumps(payload, ensure_ascii=False) + "\n```"},
    )

    with holder.SessionLocal() as session:
        block_id = session.scalar(select(EditedBlock.id).where(EditedBlock.lesson_id == lesson_id))

    client.post(
        f"/lessons/{lesson_id}/blocks/{block_id}/observacao",
        data={"observacao": "lembrar de revisar isto antes da prova de reivindicatória"},
    )

    response = client.get("/search", params={"q": "reivindicatória"})
    assert response.status_code == 200
    assert "Observação" in response.text
    assert f"/lessons/{lesson_id}/aula-editada#bloco-{block_id}" in response.text


def test_search_finds_active_definitions_and_pins_matched_term(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Usucapião", "definicao_md": "Modo de aquisição pela posse prolongada.", "citacao_literal": ""})

    response = client.get("/search", params={"q": "aquisição"})
    assert response.status_code == 200
    assert "Definição" in response.text
    assert "Usucapião" in response.text

    pinned = client.get("/search", params={"q": "usucapiao"})
    assert "🔖" in pinned.text
    assert "Usucapião" in pinned.text


def test_search_subject_filter_excludes_other_subjects(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select
    from app.models import Subject

    with holder.SessionLocal() as session:
        tgdc_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        outra_id = session.scalar(select(Subject.id).where(Subject.sigla != "TGDC"))

    client.post(
        "/materials",
        data={"titulo": "Material TGDC", "origem": "texto", "texto": "conteudo filtravel exclusivo", "subject_id": str(tgdc_id)},
    )

    response = client.get("/search", params={"q": "filtravel", "subject_id": str(outra_id)})
    assert "Material TGDC" not in response.text

    response = client.get("/search", params={"q": "filtravel", "subject_id": str(tgdc_id)})
    assert "Material TGDC" in response.text


def test_search_tipo_filter_limits_sources(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        _make_transcribed_lesson(session, ["um trecho bem especifico sobre limitacao de tipo"])

    response = client.get("/search", params={"q": "limitacao", "tipo": "material"})
    assert "Nada encontrado" in response.text

    response = client.get("/search", params={"q": "limitacao", "tipo": "transcricao"})
    assert "Aula com transcrição" in response.text


def test_save_position_persists(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson

    with holder.SessionLocal() as session:
        lesson_id = _make_transcribed_lesson(session, ["trecho"])

    response = client.post(f"/lessons/{lesson_id}/posicao", json={"posicao_s": 123.5})
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        assert session.get(Lesson, lesson_id).posicao_s == 123.5
