import io
from datetime import date

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


def test_materials_page_renders_empty(app_env):
    client = _authed_client()
    response = client.get("/materials")
    assert response.status_code == 200
    assert "Nenhum material ainda." in response.text


def test_create_texto_material_and_link_to_subject(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)

    response = client.post(
        "/materials",
        data={
            "titulo": "Resumo de posse",
            "origem": "texto",
            "texto": "Posse é o exercício de fato de poderes de propriedade.",
            "subject_id": str(subject_id),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Resumo de posse" in response.text

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material, MaterialUse

        material = session.scalar(select(Material).where(Material.titulo == "Resumo de posse"))
        assert material.origem == "texto"
        assert "exercício de fato" in material.conteudo_md
        use = session.scalar(select(MaterialUse).where(MaterialUse.material_id == material.id))
        assert use.subject_id == subject_id
        assert use.lesson_id is None


def test_create_link_material_without_subject_appears_unlinked(app_env):
    client = _authed_client()
    client.post("/materials", data={"titulo": "Site do STF", "origem": "link", "url": "https://stf.jus.br"})

    response = client.get("/materials")
    assert "Site do STF" in response.text
    assert "Não vinculados (1)" in response.text


def test_create_pdf_material_uploads_file(app_env):
    client = _authed_client()
    response = client.post(
        "/materials",
        data={"titulo": "Slide aula 1", "origem": "pdf"},
        files={"arquivo": ("slide.pdf", io.BytesIO(b"%PDF-1.4 conteudo falso"), "application/pdf")},
        follow_redirects=True,
    )
    assert response.status_code == 200

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material

        material = session.scalar(select(Material).where(Material.titulo == "Slide aula 1"))
        assert material.origem == "pdf"
        assert material.path is not None
        assert material.mime == "application/pdf"

    file_response = client.get(f"/materials/{material.id}/arquivo")
    assert file_response.status_code == 200
    assert file_response.content == b"%PDF-1.4 conteudo falso"


def test_create_pdf_material_without_file_returns_400(app_env):
    client = _authed_client()
    response = client.post("/materials", data={"titulo": "Sem arquivo", "origem": "pdf"})
    assert response.status_code == 400


def test_link_material_resolves_unlinked_box(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)

    client.post("/materials", data={"titulo": "Sem link", "origem": "texto", "texto": "conteudo"})
    with holder.SessionLocal() as session:
        from app.models import Material

        material_id = session.scalar(select(Material.id).where(Material.titulo == "Sem link"))

    client.post(f"/materials/{material_id}/vincular", data={"subject_id": str(subject_id)})

    response = client.get("/materials")
    assert "Não vinculados (0)" in response.text


def test_add_and_remove_tag(app_env):
    client = _authed_client()
    client.post("/materials", data={"titulo": "Com tag", "origem": "texto", "texto": "x"})

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material

        material_id = session.scalar(select(Material.id).where(Material.titulo == "Com tag"))

    response = client.post(f"/materials/{material_id}/tags", data={"tag": "Prova Antiga"}, follow_redirects=True)
    assert "prova antiga" in response.text  # normalizado em minúsculo

    with holder.SessionLocal() as session:
        from app.models import MaterialTag

        tag_id = session.scalar(select(MaterialTag.id).where(MaterialTag.material_id == material_id))

    response = client.post(f"/materials/{material_id}/tags/{tag_id}/remover", follow_redirects=True)
    assert "prova antiga" not in response.text


def test_set_tipo(app_env):
    client = _authed_client()
    client.post("/materials", data={"titulo": "Tipado", "origem": "texto", "texto": "x"})

    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        from app.models import Material, MaterialTipo

        material_id = session.scalar(select(Material.id).where(Material.titulo == "Tipado"))
        tipo_id = session.scalar(select(MaterialTipo.id).where(MaterialTipo.slug == "resumo"))

    client.post(f"/materials/{material_id}/tipo", data={"tipo_id": str(tipo_id)})

    with holder.SessionLocal() as session:
        from app.models import Material

        material = session.get(Material, material_id)
        assert material.tipo.slug == "resumo"


def test_sync_route_without_folder_id_configured_shows_error(app_env):
    client = _authed_client()
    response = client.post("/materials/sync", follow_redirects=True)
    assert "GOOGLE_DRIVE_FOLDER_ID" in response.text


def test_material_detail_shows_uses(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        from app.models import Lesson

        lesson = Lesson(subject_id=subject_id, titulo="Aula 1", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    client.post(
        "/materials",
        data={
            "titulo": "Vinculado a aula",
            "origem": "texto",
            "texto": "x",
            "subject_id": str(subject_id),
            "lesson_id": str(lesson_id),
        },
    )

    with holder.SessionLocal() as session:
        from app.models import Material

        material_id = session.scalar(select(Material.id).where(Material.titulo == "Vinculado a aula"))

    response = client.get(f"/materials/{material_id}")
    assert response.status_code == 200
    assert "Aula 1" in response.text


def test_lesson_detail_shows_criar_doc_button_when_subject_has_modelo(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        from app.models import Lesson, Subject

        session.get(Subject, subject_id).doc_modelo_id = "modelo-123"
        session.get(Subject, subject_id).drive_folder_id = "folder-civil"
        lesson = Lesson(subject_id=subject_id, titulo="Usucapião", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    response = client.get(f"/lessons/{lesson_id}")
    assert "Criar doc desta aula" in response.text
    assert "docs.google.com/document/d/modelo-123/copy" in response.text
    assert "folderId=folder-civil" in response.text


def test_lesson_detail_hides_criar_doc_button_without_modelo(app_env):
    client = _authed_client()
    from app.db import holder
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        from app.models import Lesson

        lesson = Lesson(subject_id=subject_id, titulo="Usucapião", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

    response = client.get(f"/lessons/{lesson_id}")
    assert "Criar doc desta aula" not in response.text


def test_update_subject_drive_settings(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)

    client.post(
        f"/subjects/{subject_id}/drive",
        data={"drive_folder_id": "folder-x", "doc_modelo_id": "modelo-y"},
    )

    with holder.SessionLocal() as session:
        from app.models import Subject

        subject = session.get(Subject, subject_id)
        assert subject.drive_folder_id == "folder-x"
        assert subject.doc_modelo_id == "modelo-y"
