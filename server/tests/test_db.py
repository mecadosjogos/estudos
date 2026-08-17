def test_wal_and_busy_timeout_are_set(app_env):
    from app.db import holder

    with holder.engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert mode.lower() == "wal"
    assert timeout == 30000


def test_seed_creates_five_subjects(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import Subject

    with holder.SessionLocal() as session:
        subjects = session.scalars(select(Subject)).all()

    siglas = {s.sigla for s in subjects}
    assert siglas == {"TGDC", "CPOL", "HIST", "TGC", "DH"}


def test_maintenance_mode_blocks_get_session(app_env):
    from app.db import get_session, maintenance_mode

    with maintenance_mode():
        try:
            next(get_session())
            raised = False
        except RuntimeError:
            raised = True
    assert raised
