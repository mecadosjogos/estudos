def test_create_backup_writes_a_file(app_env):
    from app import backup, config

    path = backup.create_backup()

    assert path.exists()
    assert path.parent == config.BACKUP_DIR


def test_retention_keeps_only_recent_backups(app_env, monkeypatch):
    from app import backup, config

    monkeypatch.setattr(config, "BACKUP_RETENTION", 2)
    for _ in range(4):
        backup.create_backup()

    remaining = list(config.BACKUP_DIR.glob("estudos-*.db"))
    assert len(remaining) == 2


def test_restore_replaces_db_and_creates_safety_copy(app_env):
    from sqlalchemy import delete

    from app import backup, config, db
    from app.models import Subject

    original_backup = backup.create_backup()

    with db.holder.SessionLocal() as session:
        session.execute(delete(Subject))
        session.commit()
    with db.holder.SessionLocal() as session:
        assert session.query(Subject).count() == 0

    safety_copy = backup.restore_from(original_backup)

    assert safety_copy.exists()
    assert safety_copy.parent == config.BACKUP_DIR / "pre-restore"

    with db.holder.SessionLocal() as session:
        assert session.query(Subject).count() == 5
