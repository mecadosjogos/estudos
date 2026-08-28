import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _lesson_with_transcript_id(session, subject_sigla="TGDC", titulo="Aula glossário") -> int:
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


def _pasted_response(termos) -> str:
    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "conceito", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [{"titulo": "Posse", "start_s": 0.0, "end_s": 5.0}],
        "guia_titulo": "Posse", "guia_secoes": [{"titulo": "Posse", "corpo": "Guia de teste."}],
        "guia_topicos": [{"titulo": "Posse"}],
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": termos, "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _termo_payload(termo="Posse", variantes=None):
    return {
        "termo": termo,
        "definicao": "Exercício de fato de poderes de propriedade.",
        "citacao_literal": "a gente chama isso de posse",
        "start_s": 0.0,
        "variantes": variantes or [],
    }


def test_accept_lesson_termo_creates_term_and_aliases(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Term, TermAlias

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response([_termo_payload(variantes=["posse direta", "posse indireta"])])},
    )

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson_id))

    response = client.post(
        f"/lessons/{lesson_id}/termos/{proposal_id}/aceitar", data={"termo": "Posse"}, follow_redirects=True
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        term = session.scalar(select(Term).where(Term.slug == "posse"))
        assert term is not None
        definition = session.get(Definition, proposal_id)
        assert definition.status == "ativo"
        assert definition.term_id == term.id
        aliases = {a.alias for a in session.scalars(select(TermAlias).where(TermAlias.term_id == term.id))}
        assert aliases == {"posse direta", "posse indireta"}


def test_discard_lesson_termo_marks_descartado(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response([_termo_payload()])})

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/termos/{proposal_id}/descartar")

    with holder.SessionLocal() as session:
        assert session.get(Definition, proposal_id).status == "descartado"


def test_accept_two_lessons_same_topic_dedupe_into_one_term(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Term

    with holder.SessionLocal() as session:
        lesson1 = _lesson_with_transcript_id(session, titulo="Aula 1")
        lesson2 = _lesson_with_transcript_id(session, titulo="Aula 2")

    client.post(f"/lessons/{lesson1}/colar-resposta", data={"resposta": _pasted_response([_termo_payload("Usucapião")])})
    client.post(f"/lessons/{lesson2}/colar-resposta", data={"resposta": _pasted_response([_termo_payload("usucapiao")])})

    with holder.SessionLocal() as session:
        p1 = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson1))
        p2 = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson2))

    client.post(f"/lessons/{lesson1}/termos/{p1}/aceitar", data={"termo": "Usucapião"})
    client.post(f"/lessons/{lesson2}/termos/{p2}/aceitar", data={"termo": "usucapiao"})

    with holder.SessionLocal() as session:
        terms = session.scalars(select(Term).where(Term.slug == "usucapiao")).all()
        assert len(terms) == 1
        definitions = session.scalars(select(Definition).where(Definition.term_id == terms[0].id)).all()
        assert len(definitions) == 2


def test_approval_screen_suggests_merge_for_similar_termo(app_env):
    client = _authed_client()

    client.post("/termos/criar", data={"termo": "Negócio jurídico", "definicao_md": "Def.", "citacao_literal": ""})

    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response([_termo_payload("Negócios jurídicos")])},
    )

    response = client.get(f"/lessons/{lesson_id}/aprovacao")
    assert "juntar em" in response.text
    assert "Negócio jurídico" in response.text


def test_accepting_similar_spelling_into_existing_term_adds_alias(app_env):
    """Micro-correção: a grafia proposta pela IA também vira alias quando
    difere do rótulo do termo alvo -- sem isso, juntar "Negócios jurídicos"
    em "Negócio jurídico" faria aquela grafia parar de casar no texto da
    aula (glossary/render.py)."""
    client = _authed_client()

    client.post("/termos/criar", data={"termo": "Negócio jurídico", "definicao_md": "Def.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Term, TermAlias

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "negocio-juridico"))
        lesson_id = _lesson_with_transcript_id(session)

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response([_termo_payload("Negócios jurídicos")])},
    )

    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson_id))

    client.post(f"/lessons/{lesson_id}/termos/{proposal_id}/aceitar", data={"termo": "Negócio jurídico"})

    with holder.SessionLocal() as session:
        terms = session.scalars(select(Term).where(Term.slug == "negocio-juridico")).all()
        assert len(terms) == 1
        alias = session.scalar(
            select(TermAlias).where(TermAlias.term_id == term_id, TermAlias.alias == "Negócios jurídicos")
        )
        assert alias is not None


def test_termo_detail_page_shows_definitions_and_variants(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(
        f"/lessons/{lesson_id}/colar-resposta",
        data={"resposta": _pasted_response([_termo_payload(variantes=["posse direta"])])},
    )
    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson_id))
    client.post(f"/lessons/{lesson_id}/termos/{proposal_id}/aceitar", data={"termo": "Posse"})

    with holder.SessionLocal() as session:
        from app.models import Term

        term_id = session.scalar(select(Term.id).where(Term.slug == "posse"))

    response = client.get(f"/termos/{term_id}")
    assert response.status_code == 200
    assert "Exercício de fato de poderes de propriedade." in response.text
    assert "posse direta" in response.text


def test_termos_list_and_search(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response([_termo_payload()])})
    with holder.SessionLocal() as session:
        proposal_id = session.scalar(select(Definition.id).where(Definition.lesson_id == lesson_id))
    client.post(f"/lessons/{lesson_id}/termos/{proposal_id}/aceitar", data={"termo": "Posse"})

    response = client.get("/termos")
    assert "Posse" in response.text

    response = client.get("/termos?q=Posse")
    assert "Posse" in response.text
    response = client.get("/termos?q=Nada")
    assert "Nenhum termo" in response.text


def test_termos_pendentes_filter_lists_ai_proposals_across_lessons(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": _pasted_response([_termo_payload()])})

    response = client.get("/termos?pendentes=1")
    assert "Posse" in response.text
    assert "Exercício de fato de poderes de propriedade." in response.text


def test_criar_termo_na_mao(app_env):
    client = _authed_client()
    response = client.post(
        "/termos/criar",
        data={"termo": "Boa-fé", "definicao_md": "Padrão de conduta esperado.", "citacao_literal": ""},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Boa-fé" in response.text
    assert "Padrão de conduta esperado." in response.text


def test_renomear_termo_keeps_slug(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Posse", "definicao_md": "Def.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Term

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "posse"))

    client.post(f"/termos/{term_id}/renomear", data={"rotulo": "Posse (direito real)"})

    with holder.SessionLocal() as session:
        term = session.get(Term, term_id)
        assert term.rotulo == "Posse (direito real)"
        assert term.slug == "posse"


def test_fundir_termos_migrates_definitions(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Negócio jurídico", "definicao_md": "Def A.", "citacao_literal": ""})
    client.post("/termos/criar", data={"termo": "Negócios jurídicos", "definicao_md": "Def B.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Term

    with holder.SessionLocal() as session:
        alvo = session.scalar(select(Term.id).where(Term.slug == "negocio-juridico"))
        origem = session.scalar(select(Term.id).where(Term.slug == "negocios-juridicos"))

    response = client.post(f"/termos/{origem}/fundir", data={"target_id": alvo}, follow_redirects=True)
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        assert session.get(Term, origem) is None
        definitions = session.scalars(select(Definition).where(Definition.term_id == alvo)).all()
        assert len(definitions) == 2


def test_adicionar_e_remover_variante(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Posse", "definicao_md": "Def.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Term, TermAlias

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "posse"))

    client.post(f"/termos/{term_id}/variantes", data={"alias": "posses"})
    with holder.SessionLocal() as session:
        alias = session.scalar(select(TermAlias).where(TermAlias.term_id == term_id, TermAlias.alias == "posses"))
        assert alias is not None
        alias_id = alias.id

    client.post(f"/termos/{term_id}/variantes/{alias_id}/remover")
    with holder.SessionLocal() as session:
        assert session.get(TermAlias, alias_id) is None


def test_alternar_destacar(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Posse", "definicao_md": "Def.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Term

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "posse"))

    client.post(f"/termos/{term_id}/destacar", data={"destacar": "false"})
    with holder.SessionLocal() as session:
        assert session.get(Term, term_id).destacar is False

    client.post(f"/termos/{term_id}/destacar", data={"destacar": "true"})
    with holder.SessionLocal() as session:
        assert session.get(Term, term_id).destacar is True


def test_descartar_definicao_nao_apaga_as_outras(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Culpa", "definicao_md": "Def civil.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Term

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "culpa"))

    client.post("/termos/criar", data={"termo": "Culpa", "definicao_md": "Def penal.", "citacao_literal": ""})

    with holder.SessionLocal() as session:
        definitions = session.scalars(select(Definition).where(Definition.term_id == term_id)).all()
        assert len(definitions) == 2
        to_discard = definitions[0].id

    client.post(f"/termos/{term_id}/definitions/{to_discard}/descartar")

    with holder.SessionLocal() as session:
        ativos = session.scalars(
            select(Definition).where(Definition.term_id == term_id, Definition.status == "ativo")
        ).all()
        assert len(ativos) == 1
        assert session.get(Definition, to_discard).status == "descartado"


def test_separar_definicao_moves_to_new_term(app_env):
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "Culpa", "definicao_md": "Definição errada de junção.", "citacao_literal": ""})

    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Term

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "culpa"))
        definition_id = session.scalar(select(Definition.id).where(Definition.term_id == term_id))

    response = client.post(
        f"/termos/{term_id}/definitions/{definition_id}/separar",
        data={"novo_termo": "Dolo"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        novo_termo = session.scalar(select(Term).where(Term.slug == "dolo"))
        assert novo_termo is not None
        assert session.get(Definition, definition_id).term_id == novo_termo.id


def test_edited_lesson_highlights_active_glossary_terms(app_env):
    """Fase 11: a marcação acontece em tempo de renderização (PLANO.md) --
    um termo já ativo no glossário precisa aparecer sublinhado na aula
    editada de QUALQUER aula, mesmo uma que não propôs esse termo."""
    client = _authed_client()

    client.post("/termos/criar", data={"termo": "Posse", "definicao_md": "Def.", "citacao_literal": ""})

    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id = _lesson_with_transcript_id(session)

    payload = {
        "resumo": "Resumo curto.",
        "aula_editada": [
            {"tipo": "normal", "texto": "A posse exige corpus e animus.", "start_s": 0.0, "end_s": 5.0},
        ],
        "indice": [], "guia_titulo": "Posse", "guia_secoes": [], "guia_topicos": [],
        "artigos": [], "datas_anunciadas": [], "cards": [],
        "termos": [], "pares_confundiveis": [], "mapa_mermaid": None, "assuntos": [],
    }
    resposta = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    client.post(f"/lessons/{lesson_id}/colar-resposta", data={"resposta": resposta})

    response = client.get(f"/lessons/{lesson_id}/aula-editada")
    assert response.status_code == 200
    assert 'class="glossary-term"' in response.text
    assert ">posse<" in response.text.lower() or ">Posse<" in response.text


def test_fixar_e_desfixar_preferencia(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Definition, Subject, Term, TermPin

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))

    client.post(
        "/termos/criar",
        data={"termo": "Culpa", "definicao_md": "Def.", "citacao_literal": "", "subject_id": subject_id},
    )

    with holder.SessionLocal() as session:
        term_id = session.scalar(select(Term.id).where(Term.slug == "culpa"))
        definition_id = session.scalar(select(Definition.id).where(Definition.term_id == term_id))

    client.post(f"/termos/{term_id}/fixar", data={"subject_id": subject_id, "definition_id": definition_id})
    with holder.SessionLocal() as session:
        pin = session.scalar(select(TermPin).where(TermPin.term_id == term_id, TermPin.subject_id == subject_id))
        assert pin is not None
        assert pin.definition_id == definition_id

    client.post(f"/termos/{term_id}/desfixar", data={"subject_id": subject_id})
    with holder.SessionLocal() as session:
        pin = session.scalar(select(TermPin).where(TermPin.term_id == term_id, TermPin.subject_id == subject_id))
        assert pin is None
