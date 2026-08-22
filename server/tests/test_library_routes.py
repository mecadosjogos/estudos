import io

import fitz
from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _subject_id(session, sigla="TGDC"):
    from sqlalchemy import select

    from app.models import Subject

    return session.scalar(select(Subject.id).where(Subject.sigla == sigla))


def _make_text_pdf_bytes(pages_text):
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_create_work_and_view_detail(app_env):
    client = _authed_client()
    response = client.post(
        "/works",
        data={"titulo": "Instituições de Direito Civil", "autores": "Caio Mário da Silva Pereira", "ano": "2020"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Instituições de Direito Civil" in response.text
    assert "PEREIRA, Caio Mário da Silva." in response.text


def test_works_list_shows_created_work(app_env):
    client = _authed_client()
    client.post("/works", data={"titulo": "Obra X"})
    response = client.get("/works")
    assert "Obra X" in response.text


def test_upload_pdf_material_creates_pages(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(
        ["Página um com bastante texto extraível de verdade, sem dúvida.", "Página dois também com bastante texto extraível."]
    )
    response = client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "2"},
        files={"arquivo": ("cap1.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Cap 1" in response.text
    assert "2/2 páginas prontas" in response.text


def test_upload_overlapping_material_without_confirmation_is_rejected(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Texto da primeira porção aqui."])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "50"},
        files={"arquivo": ("cap1.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    pdf_bytes2 = _make_text_pdf_bytes(["Texto de uma porção que colide."])
    response = client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1 de novo", "origem": "pdf", "pagina_inicial": "30", "pagina_final": "80"},
        files={"arquivo": ("cap1b.pdf", io.BytesIO(pdf_bytes2), "application/pdf")},
        follow_redirects=True,
    )
    assert "sobrep" in response.text.lower()

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material

        count = len(session.scalars(select(Material).where(Material.work_id == work_id)).all())
        assert count == 1  # o segundo upload não foi gravado


def test_upload_overlapping_material_with_confirmation_succeeds(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Texto da primeira porção aqui."])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "50"},
        files={"arquivo": ("cap1.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    pdf_bytes2 = _make_text_pdf_bytes(["Foto melhor da mesma porção."])
    response = client.post(
        f"/works/{work_id}/materiais",
        data={
            "titulo": "Cap 1 refeito",
            "origem": "pdf",
            "pagina_inicial": "30",
            "pagina_final": "80",
            "sobrepor_confirmado": "1",
        },
        files={"arquivo": ("cap1b.pdf", io.BytesIO(pdf_bytes2), "application/pdf")},
        follow_redirects=True,
    )
    assert response.status_code == 200

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material

        count = len(session.scalars(select(Material).where(Material.work_id == work_id)).all())
        assert count == 2


def test_upload_without_page_range_requires_manual_order_confirmation(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Sem numeração conhecida."])
    response = client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Fotos soltas", "origem": "pdf"},
        files={"arquivo": ("f.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        follow_redirects=True,
    )
    assert "numera" in response.text.lower() or "desconhecida" in response.text.lower()


def test_add_and_remove_work_section(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    response = client.post(
        f"/works/{work_id}/sections",
        data={"titulo": "Capítulo 1", "nivel": "1", "pagina_inicial": "1", "pagina_final": "120"},
        follow_redirects=True,
    )
    assert "Capítulo 1" in response.text
    assert "ausente" not in response.text or "Capítulo 1" in response.text

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import WorkSection

        section_id = session.scalar(select(WorkSection.id).where(WorkSection.work_id == work_id))

    response = client.post(f"/works/{work_id}/sections/{section_id}/remover", follow_redirects=True)
    assert "Capítulo 1" not in response.text


def test_coverage_map_shows_missing_section(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    client.post(
        f"/works/{work_id}/sections",
        data={"titulo": "Capítulo sem material", "nivel": "1", "pagina_inicial": "500", "pagina_final": "600"},
    )
    response = client.get(f"/works/{work_id}")
    assert "ausente" in response.text


def test_mark_usage_by_subject_with_page_range(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Constituição"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Art 1", "Art 5"])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Texto completo", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "2"},
        files={"arquivo": ("cf.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material

        material_id = session.scalar(select(Material.id).where(Material.work_id == work_id))
        subject_id = _subject_id(session, "DH")

    response = client.post(
        f"/works/{work_id}/usos",
        data={
            "material_id": str(material_id),
            "subject_id": str(subject_id),
            "pagina_inicial": "2",
            "pagina_final": "2",
            "rotulo": "art. 5º",
        },
        follow_redirects=True,
    )
    assert "DH" in response.text
    assert "art. 5º" in response.text


def test_read_work_shows_pages_in_order(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Primeiro conteúdo real da página.", "Segundo conteúdo real da página."])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "10", "pagina_final": "11"},
        files={"arquivo": ("c.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    response = client.get(f"/works/{work_id}/ler")
    assert response.status_code == 200
    assert "Primeiro conteúdo real" in response.text
    assert "p. 10" in response.text
    assert "p. 11" in response.text


def test_read_work_highlights_active_glossary_terms(app_env):
    """Fase 11: "em todo texto do app... capítulo de livro" (PLANO.md) --
    a leitura da obra também passa pela marcação do glossário."""
    client = _authed_client()
    client.post("/termos/criar", data={"termo": "posse", "definicao_md": "Def.", "citacao_literal": ""})

    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["A posse exige corpus e animus de verdade."])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "1"},
        files={"arquivo": ("c.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    response = client.get(f"/works/{work_id}/ler")
    assert response.status_code == 200
    assert 'class="glossary-term"' in response.text


def test_edit_page_protects_against_overwrite_marker(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Texto original com erro de OCR."])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "1", "pagina_final": "1"},
        files={"arquivo": ("c.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material, MaterialPage

        material_id = session.scalar(select(Material.id).where(Material.work_id == work_id))
        page_id = session.scalar(select(MaterialPage.id).where(MaterialPage.material_id == material_id))

    response = client.post(
        f"/materials/{material_id}/paginas/{page_id}/editar",
        data={"texto": "Texto corrigido à mão."},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        from app.models import MaterialPage

        page = session.get(MaterialPage, page_id)
        assert page.texto == "Texto corrigido à mão."
        assert page.editado_em is not None


def test_paste_transcription_marks_page_ok_and_logs_ai_call(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    # foto -- nasce pendente, sem texto
    response = client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Fotos", "origem": "foto", "pagina_inicial": "1", "pagina_final": "1"},
        files={"arquivos": ("p1.jpg", io.BytesIO(b"fake-jpeg-bytes"), "image/jpeg")},
        follow_redirects=True,
    )
    assert response.status_code == 200

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material, MaterialPage

        material_id = session.scalar(select(Material.id).where(Material.work_id == work_id))
        page = session.scalar(select(MaterialPage).where(MaterialPage.material_id == material_id))
        assert page.status == "pendente"
        page_id = page.id

    response = client.post(
        f"/materials/{material_id}/paginas/{page_id}/colar",
        data={"texto": "Texto transcrito da foto pela visão."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    with holder.SessionLocal() as session:
        from app.models import AiCall, MaterialPage

        page = session.get(MaterialPage, page_id)
        assert page.texto == "Texto transcrito da foto pela visão."
        assert page.extraido_por == "visao"
        assert page.editado_em is None
        assert page.ai_call_id is not None

        ai_call = session.get(AiCall, page.ai_call_id)
        assert ai_call.tipo_acao == "transcrever_pagina"
        assert ai_call.via == "manual"
        assert ai_call.custo_usd == 0.0


def test_paste_transcription_refuses_to_overwrite_edited_page(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Fotos", "origem": "foto", "pagina_inicial": "1", "pagina_final": "1"},
        files={"arquivos": ("p1.jpg", io.BytesIO(b"fake-jpeg-bytes"), "image/jpeg")},
    )

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material, MaterialPage

        material_id = session.scalar(select(Material.id).where(Material.work_id == work_id))
        page_id = session.scalar(select(MaterialPage.id).where(MaterialPage.material_id == material_id))

    client.post(f"/materials/{material_id}/paginas/{page_id}/editar", data={"texto": "Correção manual minha."})

    response = client.post(
        f"/materials/{material_id}/paginas/{page_id}/colar", data={"texto": "Tentativa de sobrescrever."}
    )
    assert response.status_code == 409

    with holder.SessionLocal() as session:
        from app.models import MaterialPage

        page = session.get(MaterialPage, page_id)
        assert page.texto == "Correção manual minha."


def test_mark_page_error_does_not_block_other_pages(app_env):
    client = _authed_client()
    response = client.post("/works", data={"titulo": "Obra"}, follow_redirects=True)
    work_id = int(response.url.path.split("/")[-1])

    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Fotos", "origem": "foto", "pagina_inicial": "1", "pagina_final": "2"},
        files=[
            ("arquivos", ("p1.jpg", io.BytesIO(b"a"), "image/jpeg")),
            ("arquivos", ("p2.jpg", io.BytesIO(b"b"), "image/jpeg")),
        ],
    )

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material, MaterialPage

        material_id = session.scalar(select(Material.id).where(Material.work_id == work_id))
        pages = session.scalars(select(MaterialPage).where(MaterialPage.material_id == material_id).order_by(MaterialPage.ordem)).all()
        page1_id, page2_id = pages[0].id, pages[1].id

    response = client.post(f"/materials/{material_id}/paginas/{page1_id}/erro", data={"erro": "letra ilegível"})
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        from app.models import MaterialPage

        page1 = session.get(MaterialPage, page1_id)
        page2 = session.get(MaterialPage, page2_id)
        assert page1.status == "erro"
        assert page1.erro == "letra ilegível"
        assert page2.status == "pendente"  # não afetada


def test_cite_work_returns_plain_text_with_page(app_env):
    client = _authed_client()
    response = client.post(
        "/works", data={"titulo": "Obra", "autores": "Fulano de Tal", "ano": "2021"}, follow_redirects=True
    )
    work_id = int(response.url.path.split("/")[-1])

    response = client.get(f"/works/{work_id}/citar?pagina=42")
    assert response.status_code == 200
    assert "p. 42." in response.text


def test_download_work_includes_reference_header_and_page_markers(app_env):
    client = _authed_client()
    response = client.post(
        "/works", data={"titulo": "Obra Baixável", "autores": "Fulano de Tal", "ano": "2022"}, follow_redirects=True
    )
    work_id = int(response.url.path.split("/")[-1])

    pdf_bytes = _make_text_pdf_bytes(["Conteúdo de teste para baixar depois."])
    client.post(
        f"/works/{work_id}/materiais",
        data={"titulo": "Cap 1", "origem": "pdf", "pagina_inicial": "5", "pagina_final": "5"},
        files={"arquivo": ("c.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    response = client.get(f"/works/{work_id}/baixar")
    assert response.status_code == 200
    assert "TAL, Fulano de." in response.text
    assert "p. 5" in response.text
    assert "Conteúdo de teste" in response.text
    assert "Content-Disposition" in response.headers
