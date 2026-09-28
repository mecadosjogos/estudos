"""Aula de consolidação (PLANO.md, "Aula de consolidação"): guias de várias
aulas viram um guia único, com índice hierárquico 8 / 8.1 / 8.1a."""

from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _aula_com_guia(session, titulo, dia, guia_md):
    from sqlalchemy import select

    from app.ai.guia_parser import parse_guia_markdown
    from app.ai.pipeline import persistir_guia
    from app.models import Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "HIST"))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=dia)
    session.add(lesson)
    session.flush()
    persistir_guia(session, lesson, parse_guia_markdown(guia_md))
    session.commit()
    return lesson.id


GUIA_A = """# Egito e hebreus

## 1. Direito egípcio

Nos tribunais egípcios, **acusadores e acusados representavam a si próprios**.

## 2. Retomada

O **Código de Ur** antecede o **Código de Hamurabi**.
"""

GUIA_B = """# Hebreus e gregos

## 1. Direito hebraico

O **Sinédrio** era o tribunal dos setenta.

## 2. Direito grego

As **Leis de Dracon** eram severas.
"""

CONSOLIDADO = """```markdown
# História do Direito — consolidação

## Árvore de conhecimento
- Direito antigo
    - Egito

## Direito egípcio
### O processo
#### Representação
Nos tribunais egípcios, **acusadores e acusados representavam a si próprios**.
#### Códigos
O **Código de Ur** antecede o **Código de Hamurabi**.
### Fontes
Texto.

## Direito hebraico
O **Sinédrio** era o tribunal dos setenta. **Moisés** inventado.
```"""


def _duas_aulas(holder):
    with holder.SessionLocal() as session:
        a = _aula_com_guia(session, "Aula 1", date(2026, 7, 1), GUIA_A)
        b = _aula_com_guia(session, "Aula 2", date(2026, 9, 28), GUIA_B)
    return a, b


def test_criar_consolidacao_pelo_formulario(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Subject

        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "HIST"))

    form = client.get(f"/subjects/{subject_id}/consolidar")
    assert form.status_code == 200
    assert "Consolidação aulas 01/07 até 28/09" in form.text

    resp = client.post(
        f"/subjects/{subject_id}/consolidar",
        data={"titulo": "Consolidação aulas 01/07 até 28/09", "aula_ids": [str(b), str(a)]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    lesson_id = int(resp.headers["location"].rsplit("/", 1)[1])

    with holder.SessionLocal() as session:
        import json

        from app.models import Lesson

        lesson = session.get(Lesson, lesson_id)
        assert lesson.tipo == "consolidacao"
        assert json.loads(lesson.consolidacao_fontes_json) == [a, b]  # ordem cronológica
        assert lesson.data == date(2026, 9, 28)

    pagina = client.get(f"/lessons/{lesson_id}")
    assert "/consolidar-guia" in pagina.text
    assert "Subir áudio" not in pagina.text


def test_consolidacao_precisa_de_duas_aulas(app_env):
    client = _authed_client()
    from app.db import holder

    a, _b = _duas_aulas(holder)
    with holder.SessionLocal() as session:
        from app.models import Lesson

        subject_id = session.get(Lesson, a).subject_id
    resp = client.post(
        f"/subjects/{subject_id}/consolidar", data={"titulo": "x", "aula_ids": [str(a)]}, follow_redirects=False
    )
    assert "erro=" in resp.headers["location"]


def _consolidacao(holder, a, b):
    from app.ai.consolidacao import criar_consolidacao
    from app.models import Lesson

    with holder.SessionLocal() as session:
        subject_id = session.get(Lesson, a).subject_id
        return criar_consolidacao(session, subject_id, [a, b], "").id


def test_pacote_traz_os_guias_das_fontes(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    lesson_id = _consolidacao(holder, a, b)

    resp = client.get(f"/lessons/{lesson_id}/consolidacao/pacote.md")
    assert resp.status_code == 200
    assert "Trocar as palavras de um conceito" in resp.text
    assert resp.text.index("Egito e hebreus") < resp.text.index("Hebreus e gregos")
    assert "<<<FIM GUIA>>>" in resp.text


def test_colar_consolidado_grava_guia_e_relatorio(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    lesson_id = _consolidacao(holder, a, b)

    resp = client.post(f"/lessons/{lesson_id}/consolidacao/colar-resposta", data={"resposta": CONSOLIDADO})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["secoes"] == 2
    assert corpo["subtitulos"] == 2
    assert corpo["conceitos"] == 2
    assert corpo["relatorio"]["perdidos"] == ["Leis de Dracon"]
    assert corpo["relatorio"]["externos"] == ["Moisés"]

    with holder.SessionLocal() as session:
        from app.models import GuiaSecao, Lesson, TranscriptionJob

        lesson = session.get(Lesson, lesson_id)
        assert lesson.guia_titulo == "História do Direito — consolidação"
        assert session.query(GuiaSecao).filter_by(lesson_id=lesson_id).count() == 2
        # cache numerado pro .md/PDF
        assert "## Índice" in lesson.guia_md
        assert "### 1.1 O processo" in lesson.guia_md
        assert "#### 1.1b Códigos" in lesson.guia_md
        assert "{#" not in lesson.guia_md
        # narração ligada, como nas aulas normais
        assert session.query(TranscriptionJob).filter_by(lesson_id=lesson_id, target="tts_guia").count() == 1

    guia = client.get(f"/lessons/{lesson_id}/guia")
    assert guia.status_code == 200
    assert "Índice" in guia.text
    assert 'href="#secao-1-1a"' in guia.text
    assert 'id="secao-1-1a"' in guia.text
    assert "1.1a Representação" in guia.text
    assert "Sumário" not in guia.text


def test_colar_rejeita_aula_normal(app_env):
    client = _authed_client()
    from app.db import holder

    a, _b = _duas_aulas(holder)
    resp = client.post(f"/lessons/{a}/consolidacao/colar-resposta", data={"resposta": CONSOLIDADO})
    assert resp.status_code == 404


def test_upload_de_audio_recusado_na_consolidacao(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    lesson_id = _consolidacao(holder, a, b)
    assert client.get(f"/upload?lesson_id={lesson_id}").status_code == 400


def test_aula_normal_mantem_sumario_plano(app_env):
    client = _authed_client()
    from app.db import holder

    a, _b = _duas_aulas(holder)
    guia = client.get(f"/lessons/{a}/guia")
    assert "Sumário" in guia.text
    assert "guia-indice" not in guia.text


def test_numeracao_hierarquica():
    from app.ai.guia_numeracao import numerar_consolidado

    corpo = "#### solto\nx\n### A\n#### a1\n#### a2\n```\n### não é título\n```\n### B\n##### fundo"
    [s] = numerar_consolidado([("Tema", corpo)])
    assert s.corpo.split("\n")[0] == "#### 1a solto {#secao-1a}"
    assert "### 1.1 A {#secao-1-1}" in s.corpo
    assert "#### 1.1b a2 {#secao-1-1b}" in s.corpo
    assert "### não é título" in s.corpo
    assert "### 1.2 B {#secao-1-2}" in s.corpo
    assert "##### fundo" in s.corpo
    assert [n["numero"] for n in s.indice] == ["1a", "1.1", "1.2"]
    assert [n["numero"] for n in s.indice[1]["filhos"]] == ["1.1a", "1.1b"]
