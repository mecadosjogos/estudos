"""Guia "Focado" (consolidação com foco): bloco "Foco deste guia" no topo,
selo nos temas do foco e o guia continuando inteiro -- ver
ai/consolidacao.py e ai/guia_numeracao.py."""

import json
from datetime import date

from test_consolidacao import _authed_client, _consolidacao, _duas_aulas

ORIENTACAO = """“Grego e romano. Grego e romano. Só.”
A prova será com dez questões. O "ou" deve ser erro da transcrição."""

FOCADO = """# História do Direito — focado

## Foco deste guia
- **Foco:** prova de História do Direito
- **O que cai:** "Grego e romano. Grego e romano. Só."
- *(observação) o "ou" do formato deve ser erro da transcrição*

## Árvore de conhecimento
- Direito antigo

## Direito egípcio
### O processo
Nos tribunais egípcios, **acusadores e acusados representavam a si próprios**.
### Códigos
O **Código de Ur** antecede o **Código de Hamurabi**.

## Direito hebraico
O **Sinédrio** era o tribunal dos setenta.

## Direito grego {foco}
### Leis
As **Leis de Dracon** eram severas.

**Atenção da professora:** "Grego e romano. Grego e romano. Só."
### Tribunais
Texto.
"""


def _focado(holder, a, b, **kw):
    from app.ai.consolidacao import criar_consolidacao
    from app.models import Lesson

    with holder.SessionLocal() as session:
        subject_id = session.get(Lesson, a).subject_id
        return criar_consolidacao(session, subject_id, [a, b], "", foco_orientacao=ORIENTACAO, **kw).id


def test_criar_guia_focado_pelo_formulario(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Exam, Lesson

    a, b = _duas_aulas(holder)
    with holder.SessionLocal() as session:
        subject_id = session.get(Lesson, a).subject_id
        exam = Exam(subject_id=subject_id, titulo="P1", data=date(2026, 11, 20))
        session.add(exam)
        session.commit()
        exam_id = exam.id

    form = client.get(f"/subjects/{subject_id}/focado")
    assert form.status_code == 200
    assert "Focado — Prova" in form.text
    assert 'data-titulo="P1"' in form.text

    # sem foco escrito, não cria
    resp = client.post(f"/subjects/{subject_id}/focado", data={"aula_ids": [str(a), str(b)]}, follow_redirects=False)
    assert "erro=" in resp.headers["location"]

    resp = client.post(
        f"/subjects/{subject_id}/focado",
        data={"titulo": "", "foco_orientacao": ORIENTACAO, "exam_id": str(exam_id), "aula_ids": [str(a), str(b)]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    lesson_id = int(resp.headers["location"].rsplit("/", 1)[1])

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        assert lesson.focado
        assert lesson.titulo == "Focado — P1"
        assert lesson.exam_id == exam_id
        assert lesson.foco_orientacao == ORIENTACAO

    pagina = client.get(f"/lessons/{lesson_id}")
    assert "Guia focado" in pagina.text
    assert "Grego e romano" in pagina.text
    assert "Corrigir o foco" in pagina.text

    materia = client.get(f"/subjects/{subject_id}")
    assert "Criar guia focado" in materia.text
    assert ">focado</span>" in materia.text


def test_prova_de_outra_materia_e_recusada(app_env):
    from app.ai.consolidacao import criar_consolidacao
    from app.ai.pipeline import ProcessingError
    from app.db import holder
    from app.models import Exam, Lesson, Subject

    a, b = _duas_aulas(holder)
    with holder.SessionLocal() as session:
        subject_id = session.get(Lesson, a).subject_id
        outra = session.query(Subject).filter(Subject.id != subject_id).first()
        exam = Exam(subject_id=outra.id, titulo="P1", data=date(2026, 11, 20))
        session.add(exam)
        session.commit()
        try:
            criar_consolidacao(session, subject_id, [a, b], "", foco_orientacao="x", exam_id=exam.id)
        except ProcessingError:
            pass
        else:
            raise AssertionError("aceitou prova de outra matéria")


def test_pacote_focado_traz_regras_e_orientacao(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    focado = _focado(holder, a, b)
    comum = _consolidacao(holder, a, b)

    texto = client.get(f"/lessons/{focado}/consolidacao/pacote.md").text
    assert "Este guia é FOCADO" in texto
    assert "<<<INÍCIO ORIENTAÇÃO>>>" in texto
    assert "Grego e romano. Grego e romano. Só." in texto
    assert "Nenhuma prova cadastrada" in texto
    # regras do foco antes dos guias-fonte
    assert texto.index("Este guia é FOCADO") < texto.index("<<<INÍCIO GUIA")

    assert "Este guia é FOCADO" not in client.get(f"/lessons/{comum}/consolidacao/pacote.md").text


def test_colar_focado_separa_bloco_e_marcas(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import GuiaSecao, Lesson

    a, b = _duas_aulas(holder)
    lesson_id = _focado(holder, a, b)

    resp = client.post(f"/lessons/{lesson_id}/consolidacao/colar-resposta", data={"resposta": FOCADO})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["secoes"] == 3  # o bloco de foco não vira seção
    assert corpo["foco"] == {"marcados": ["3 Direito grego"], "atencao": 1}
    assert corpo["relatorio"]["perdidos"] == []
    assert corpo["relatorio"]["externos"] == []

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        assert lesson.foco_md.startswith("- **Foco:** prova")
        assert json.loads(lesson.foco_marcas_json) == ["direito grego"]
        # o marcador sai do texto: narração, exercícios e dissertativas não o veem
        secoes = session.query(GuiaSecao).filter_by(lesson_id=lesson_id).order_by(GuiaSecao.ordem).all()
        assert [s.titulo for s in secoes] == ["Direito egípcio", "Direito hebraico", "Direito grego"]
        assert all("{foco}" not in s.corpo for s in secoes)
        # cache .md/PDF: bloco no topo, estrela no título e no índice
        assert lesson.guia_md.index("## Foco deste guia") < lesson.guia_md.index("## Árvore de conhecimento")
        assert "## 3. Direito grego ★" in lesson.guia_md
        assert "- 3 Direito grego ★" in lesson.guia_md
        assert "{foco}" not in lesson.guia_md

    guia = client.get(f"/lessons/{lesson_id}/guia")
    assert "Foco deste guia" in guia.text
    assert 'class="card guia-foco' in guia.text
    assert "Guia focado a partir" in guia.text
    assert guia.text.count('<span class="selo-foco">★ foco</span>') >= 3  # índice + título + legenda
    assert "guia-bloco--foco" in guia.text


def test_editar_secao_mantem_a_marca(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import GuiaSecao

    a, b = _duas_aulas(holder)
    lesson_id = _focado(holder, a, b)
    client.post(f"/lessons/{lesson_id}/consolidacao/colar-resposta", data={"resposta": FOCADO})
    with holder.SessionLocal() as session:
        secao = session.query(GuiaSecao).filter_by(lesson_id=lesson_id, titulo="Direito egípcio").one()
        secao_id = secao.id

    resp = client.post(f"/lessons/{lesson_id}/guia/secoes/{secao_id}", data={"corpo": "### O processo\nTexto novo."})
    assert resp.status_code == 200
    with holder.SessionLocal() as session:
        from app.models import Lesson

        assert "## 3. Direito grego ★" in session.get(Lesson, lesson_id).guia_md


def test_atencao_colada_no_paragrafo_nao_conta(app_env):
    """O relatório só conta o destaque que vira bloco na tela."""
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    lesson_id = _focado(holder, a, b)
    colado = FOCADO.replace('severas.\n\n**Atenção da professora:**', 'severas.\n**Atenção da professora:**')
    assert colado != FOCADO
    resp = client.post(f"/lessons/{lesson_id}/consolidacao/colar-resposta", data={"resposta": colado})
    assert resp.json()["foco"]["atencao"] == 0


def test_focado_sem_bloco_de_foco_e_recusado(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    lesson_id = _focado(holder, a, b)
    sem_bloco = FOCADO.replace("## Foco deste guia\n", "## Introdução\n")
    resp = client.post(f"/lessons/{lesson_id}/consolidacao/colar-resposta", data={"resposta": sem_bloco})
    assert resp.status_code == 400


def test_consolidacao_comum_recusa_foco(app_env):
    client = _authed_client()
    from app.db import holder

    a, b = _duas_aulas(holder)
    lesson_id = _consolidacao(holder, a, b)
    resp = client.post(f"/lessons/{lesson_id}/consolidacao/colar-resposta", data={"resposta": FOCADO})
    assert resp.status_code == 400


def test_corrigir_foco(app_env):
    client = _authed_client()
    from app.db import holder
    from app.models import Lesson

    a, b = _duas_aulas(holder)
    lesson_id = _focado(holder, a, b)
    resp = client.post(f"/lessons/{lesson_id}/foco", data={"foco_orientacao": "  "}, follow_redirects=False)
    assert "erro_foco=" in resp.headers["location"]
    resp = client.post(f"/lessons/{lesson_id}/foco", data={"foco_orientacao": "Só romano."}, follow_redirects=False)
    assert resp.status_code == 303
    with holder.SessionLocal() as session:
        assert session.get(Lesson, lesson_id).foco_orientacao == "Só romano."
    comum = _consolidacao(holder, a, b)
    assert client.post(f"/lessons/{comum}/foco", data={"foco_orientacao": "x"}).status_code == 404


def test_marcas_de_foco_na_numeracao():
    from app.ai.guia_numeracao import extrair_marcas, numerar_consolidado, titulos_marcados

    md, marcados = extrair_marcas(
        "## Romano\n### Fase clássica {foco}\n### Pós-clássica   {foco}\n```\n### x {foco}\n```\n## Grego {foco}"
    )
    assert "### x {foco}" in md  # dentro de bloco de código fica
    assert md.count("{foco}") == 1
    assert marcados == ["fase classica", "pos-classica", "grego"]

    secoes = [("Romano", "### Fase clássica\n### Pós-clássica\n### Arcaica"), ("Grego", "Texto.")]
    numeradas = numerar_consolidado(secoes, marcados=frozenset(marcados))
    assert "### 1.1 Fase clássica {#secao-1-1 .foco}" in numeradas[0].corpo
    assert "### 1.3 Arcaica {#secao-1-3}" in numeradas[0].corpo
    assert numeradas[1].foco and not numeradas[0].foco
    assert titulos_marcados(numeradas) == ["1.1 Fase clássica", "1.2 Pós-clássica", "2 Grego"]
    sem_ancora = numerar_consolidado(secoes, com_ancora=False, marcados=frozenset(marcados))
    assert "### 1.2 Pós-clássica ★" in sem_ancora[0].corpo


def test_rotulo_atencao_da_professora():
    from app.markdown_render import render_markdown

    html = render_markdown('**Atenção da professora:** "dois crimes"\n\n**Atenção:** outro')
    assert "guia-bloco--foco" in html
    assert "guia-bloco--atencao" in html
    assert render_markdown("### Leis {#secao-1-1 .foco}").count('class="foco"') == 1
