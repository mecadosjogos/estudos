from datetime import date, datetime, timezone

from app.library.gdocs import DriveFile, FakeGoogleDriveClient, sync_drive_folder


def _subject_id(session, sigla="TGDC"):
    from sqlalchemy import select

    from app.models import Subject

    return session.scalar(select(Subject.id).where(Subject.sigla == sigla))


def test_sync_creates_material_with_converted_markdown(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        client = FakeGoogleDriveClient(
            files_by_folder={
                "root": [
                    DriveFile(id="doc1", name="Anotações soltas", modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc)),
                ]
            },
            html_by_id={"doc1": "<h1>Posse</h1><p><b>Corpus</b> e animus.</p>"},
        )
        resumo = sync_drive_folder(session, client, "root")
        assert resumo == {"synced": 1, "failed": 0, "skipped": 0, "total": 1}

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material

        material = session.scalar(select(Material).where(Material.gdoc_id == "doc1"))
        assert material.origem == "gdoc"
        assert material.status == "ok"
        assert "# Posse" in material.conteudo_md
        assert "**Corpus**" in material.conteudo_md


def test_sync_is_incremental_skips_unchanged_modified_time(app_env):
    from app.db import holder

    modified = datetime(2026, 3, 12, tzinfo=timezone.utc)
    client = FakeGoogleDriveClient(
        files_by_folder={"root": [DriveFile(id="doc1", name="Doc", modified_time=modified)]},
        html_by_id={"doc1": "<p>v1</p>"},
    )

    with holder.SessionLocal() as session:
        sync_drive_folder(session, client, "root")

    # segunda sync com o MESMO modified_time e HTML diferente -- não deve
    # reprocessar (a API real nem devolveria o arquivo se nada mudou, mas
    # o teste garante que o código também não reprocessa por conta própria)
    client2 = FakeGoogleDriveClient(
        files_by_folder={"root": [DriveFile(id="doc1", name="Doc", modified_time=modified)]},
        html_by_id={"doc1": "<p>v2 -- não deveria aparecer</p>"},
    )
    with holder.SessionLocal() as session:
        resumo = sync_drive_folder(session, client2, "root")
        assert resumo["skipped"] == 1
        assert resumo["synced"] == 0

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material

        material = session.scalar(select(Material).where(Material.gdoc_id == "doc1"))
        assert "v1" in material.conteudo_md
        assert "v2" not in material.conteudo_md


def test_sync_reprocesses_when_modified_time_changes(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        client = FakeGoogleDriveClient(
            files_by_folder={"root": [DriveFile(id="doc1", name="Doc", modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc))]},
            html_by_id={"doc1": "<p>v1</p>"},
        )
        sync_drive_folder(session, client, "root")

    with holder.SessionLocal() as session:
        client2 = FakeGoogleDriveClient(
            files_by_folder={"root": [DriveFile(id="doc1", name="Doc", modified_time=datetime(2026, 3, 13, tzinfo=timezone.utc))]},
            html_by_id={"doc1": "<p>v2</p>"},
        )
        resumo = sync_drive_folder(session, client2, "root")
        assert resumo["synced"] == 1

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material

        material = session.scalar(select(Material).where(Material.gdoc_id == "doc1"))
        assert "v2" in material.conteudo_md


def test_sync_records_error_without_blocking_other_docs(app_env):
    from app.db import holder

    class BrokenExportClient(FakeGoogleDriveClient):
        def export_html(self, file_id):
            if file_id == "broken":
                raise RuntimeError("permissão negada")
            return super().export_html(file_id)

    with holder.SessionLocal() as session:
        client = BrokenExportClient(
            files_by_folder={
                "root": [
                    DriveFile(id="broken", name="Doc quebrado", modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc)),
                    DriveFile(id="ok", name="Doc ok", modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc)),
                ]
            },
            html_by_id={"ok": "<p>tudo bem</p>"},
        )
        resumo = sync_drive_folder(session, client, "root")
        assert resumo["synced"] == 1
        assert resumo["failed"] == 1

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material

        broken = session.scalar(select(Material).where(Material.gdoc_id == "broken"))
        assert broken.status == "erro"
        assert "permissão negada" in broken.sync_error
        ok = session.scalar(select(Material).where(Material.gdoc_id == "ok"))
        assert ok.status == "ok"


def test_sync_auto_links_material_to_subject_via_folder(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        from app.models import Subject

        session.get(Subject, subject_id).drive_folder_id = "folder-civil"
        session.commit()

        client = FakeGoogleDriveClient(
            files_by_folder={
                "root": [],
                "folder-civil": [
                    DriveFile(
                        id="doc1", name="Resumo geral", parents=["folder-civil"],
                        modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc),
                    ),
                ],
            },
            html_by_id={"doc1": "<p>resumo</p>"},
        )
        sync_drive_folder(session, client, "root")

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material, MaterialUse

        material = session.scalar(select(Material).where(Material.gdoc_id == "doc1"))
        use = session.scalar(select(MaterialUse).where(MaterialUse.material_id == material.id))
        assert use is not None
        assert use.subject_id == subject_id
        assert use.lesson_id is None  # material da matéria, sem aula específica


def test_sync_auto_links_material_to_lesson_by_filename_date(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        from app.models import Lesson, Subject

        session.get(Subject, subject_id).drive_folder_id = "folder-civil"
        lesson = Lesson(subject_id=subject_id, titulo="Posse", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id

        client = FakeGoogleDriveClient(
            files_by_folder={
                "root": [],
                "folder-civil": [
                    DriveFile(
                        id="doc1", name="2026-03-12 anotações", parents=["folder-civil"],
                        modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc),
                    ),
                ],
            },
            html_by_id={"doc1": "<p>anotações da aula</p>"},
        )
        sync_drive_folder(session, client, "root")

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material, MaterialUse

        material = session.scalar(select(Material).where(Material.gdoc_id == "doc1"))
        use = session.scalar(select(MaterialUse).where(MaterialUse.material_id == material.id))
        assert use.lesson_id == lesson_id


def test_sync_leaves_material_unlinked_when_no_folder_matches(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        client = FakeGoogleDriveClient(
            files_by_folder={
                "root": [
                    DriveFile(id="doc1", name="Doc solto", parents=["some-other-folder"], modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc)),
                ],
            },
            html_by_id={"doc1": "<p>solto</p>"},
        )
        sync_drive_folder(session, client, "root")

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material, MaterialUse

        material = session.scalar(select(Material).where(Material.gdoc_id == "doc1"))
        use = session.scalar(select(MaterialUse).where(MaterialUse.material_id == material.id))
        assert use is None  # cai em "Não vinculados"


def test_sync_does_not_overwrite_manual_link_on_resync(app_env):
    """Uma vez vinculado (automático ou à mão), a próxima sync não pode
    trocar por baixo dos panos -- ver library/gdocs.py::_link_material."""
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session, "TGC")
        client = FakeGoogleDriveClient(
            files_by_folder={
                "root": [DriveFile(id="doc1", name="Doc", modified_time=datetime(2026, 3, 12, tzinfo=timezone.utc))],
            },
            html_by_id={"doc1": "<p>v1</p>"},
        )
        sync_drive_folder(session, client, "root")

        from sqlalchemy import select

        from app.models import Material, MaterialUse

        material_id = session.scalar(select(Material.id).where(Material.gdoc_id == "doc1"))
        session.add(MaterialUse(material_id=material_id, subject_id=subject_id))  # vínculo manual
        session.commit()

    with holder.SessionLocal() as session:
        client2 = FakeGoogleDriveClient(
            files_by_folder={
                "root": [DriveFile(id="doc1", name="Doc", modified_time=datetime(2026, 3, 13, tzinfo=timezone.utc))],
            },
            html_by_id={"doc1": "<p>v2</p>"},
        )
        sync_drive_folder(session, client2, "root")

    with holder.SessionLocal() as session:
        from sqlalchemy import select

        from app.models import Material, MaterialUse

        material_id = session.scalar(select(Material.id).where(Material.gdoc_id == "doc1"))
        uses = session.scalars(select(MaterialUse).where(MaterialUse.material_id == material_id)).all()
        assert len(uses) == 1
        assert uses[0].subject_id == subject_id
