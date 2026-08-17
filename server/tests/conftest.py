import os
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Isola cada teste com seu próprio banco e diretório de backup."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "estudos.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    # Módulos já podem ter sido importados por outro teste com config antiga;
    # força reimport para pegar as env vars isoladas deste teste.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    from app import config

    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(SERVER_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.DATABASE_PATH}")
    command.upgrade(alembic_cfg, "head")

    yield tmp_path
