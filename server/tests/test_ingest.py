import fitz
import pytest


def _make_text_pdf(path, pages_text):
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _make_mixed_pdf(path, text_pages, scanned_pages):
    """PDF com N páginas de texto seguidas de M páginas escaneadas --
    testa que ingest_pdf trata cada página pelo que ela é, não pelo
    arquivo inteiro."""
    doc = fitz.open()
    for text in text_pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    for _ in range(scanned_pages):
        page = doc.new_page()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), False)
        pixmap.set_rect(pixmap.irect, (255, 255, 255))
        page.insert_image(page.rect, pixmap=pixmap)
    doc.save(str(path))
    doc.close()


def test_ingest_photos_creates_pending_pages_in_order(app_env):
    from app.db import holder
    from app.library.ingest import ingest_photos
    from app.models import Material, MaterialPage, Work

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        material = Material(titulo="Cap 1", origem="foto", work_id=work.id, pagina_inicial=247)
        session.add(material)
        session.flush()

        ingest_photos(session, material, ["/tmp/p1.jpg", "/tmp/p2.jpg", "/tmp/p3.jpg"])
        session.commit()
        material_id = material.id

    with holder.SessionLocal() as session:
        pages = session.query(MaterialPage).filter_by(material_id=material_id).order_by(MaterialPage.ordem).all()
        assert len(pages) == 3
        assert [p.status for p in pages] == ["pendente", "pendente", "pendente"]
        assert [p.pagina_obra for p in pages] == [247, 248, 249]
        assert pages[0].image_path == "/tmp/p1.jpg"


def test_ingest_photos_without_pagina_inicial_leaves_pagina_obra_null(app_env):
    """`ordem_manual` -- numeração real desconhecida (PLANO.md)."""
    from app.db import holder
    from app.library.ingest import ingest_photos
    from app.models import Material, MaterialPage, Work

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        material = Material(titulo="Fotos soltas", origem="foto", work_id=work.id, ordem_manual=1)
        session.add(material)
        session.flush()

        ingest_photos(session, material, ["/tmp/a.jpg"])
        session.commit()
        material_id = material.id

    with holder.SessionLocal() as session:
        page = session.query(MaterialPage).filter_by(material_id=material_id).one()
        assert page.pagina_obra is None


def test_ingest_pdf_extracts_native_text_pages_as_ok(app_env, tmp_path):
    from app.db import holder
    from app.library.ingest import ingest_pdf
    from app.models import Material, MaterialPage, Work

    pdf_path = tmp_path / "capitulo.pdf"
    _make_text_pdf(pdf_path, ["Página um com bastante conteúdo de texto real.", "Página dois também com texto."])

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        material = Material(titulo="Capítulo", origem="pdf", work_id=work.id, pagina_inicial=1, path=str(pdf_path))
        session.add(material)
        session.flush()

        ingest_pdf(session, material)
        session.commit()
        material_id = material.id

    with holder.SessionLocal() as session:
        pages = session.query(MaterialPage).filter_by(material_id=material_id).order_by(MaterialPage.ordem).all()
        assert len(pages) == 2
        assert all(p.status == "ok" for p in pages)
        assert all(p.extraido_por == "nativo" for p in pages)
        assert "Página um" in pages[0].texto
        assert pages[0].pagina_obra == 1
        assert pages[1].pagina_obra == 2


def test_ingest_pdf_renders_scanned_pages_as_pending_images(app_env, tmp_path):
    from app.db import holder
    from app.library.ingest import ingest_pdf
    from app.models import Material, MaterialPage, Work

    pdf_path = tmp_path / "escaneado.pdf"
    _make_mixed_pdf(pdf_path, text_pages=[], scanned_pages=1)

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        material = Material(titulo="Escaneado", origem="pdf", work_id=work.id, path=str(pdf_path))
        session.add(material)
        session.flush()

        ingest_pdf(session, material)
        session.commit()
        material_id = material.id

    with holder.SessionLocal() as session:
        page = session.query(MaterialPage).filter_by(material_id=material_id).one()
        assert page.status == "pendente"
        assert page.texto is None
        assert page.image_path != str(pdf_path)
        import os

        assert os.path.exists(page.image_path)


def test_ingest_pdf_handles_mixed_native_and_scanned_pages(app_env, tmp_path):
    from app.db import holder
    from app.library.ingest import ingest_pdf
    from app.models import Material, MaterialPage, Work

    pdf_path = tmp_path / "misto.pdf"
    _make_mixed_pdf(pdf_path, text_pages=["Texto real de uma página nativa aqui."], scanned_pages=1)

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        material = Material(titulo="Misto", origem="pdf", work_id=work.id, path=str(pdf_path))
        session.add(material)
        session.flush()

        ingest_pdf(session, material)
        session.commit()
        material_id = material.id

    with holder.SessionLocal() as session:
        pages = session.query(MaterialPage).filter_by(material_id=material_id).order_by(MaterialPage.ordem).all()
        assert pages[0].status == "ok"
        assert pages[0].extraido_por == "nativo"
        assert pages[1].status == "pendente"


def test_find_overlapping_materials_detects_page_range_collision(app_env):
    from app.db import holder
    from app.library.ingest import find_overlapping_materials
    from app.models import Material, Work

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        existing = Material(titulo="Existente", origem="pdf", work_id=work.id, pagina_inicial=1, pagina_final=120)
        session.add(existing)
        session.commit()
        work_id = work.id

    with holder.SessionLocal() as session:
        overlapping = find_overlapping_materials(session, work_id, 100, 150)
        assert len(overlapping) == 1
        assert overlapping[0].titulo == "Existente"

        no_overlap = find_overlapping_materials(session, work_id, 121, 200)
        assert no_overlap == []


def test_find_overlapping_materials_excludes_given_material_id(app_env):
    """Editar o intervalo do próprio material não deve acusar sobreposição
    contra si mesmo."""
    from app.db import holder
    from app.library.ingest import find_overlapping_materials
    from app.models import Material, Work

    with holder.SessionLocal() as session:
        work = Work(titulo="Obra Teste")
        session.add(work)
        session.flush()
        material = Material(titulo="Mat", origem="pdf", work_id=work.id, pagina_inicial=1, pagina_final=50)
        session.add(material)
        session.commit()
        work_id = work.id
        material_id = material.id

    with holder.SessionLocal() as session:
        overlapping = find_overlapping_materials(session, work_id, 1, 50, exclude_material_id=material_id)
        assert overlapping == []
