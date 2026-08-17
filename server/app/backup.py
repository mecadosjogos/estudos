"""Backup e restauração do SQLite (PLANO.md, fase 1: "Base, backup e restauração").

Só o banco é copiado — mp3 e originais ficam de fora porque são reconstruíveis a
partir de `archive/` no PC. Restaurar troca o arquivo sob modo manutenção: o pool
de conexões é fechado antes, para não corromper o WAL (ver db.maintenance_mode).
"""

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config, db


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def create_backup(dest_dir: Path | None = None) -> Path:
    """Copia o banco de forma consistente (API de backup do sqlite3, segura com WAL
    e sem precisar parar o servidor) e aplica a retenção configurada."""
    dest_dir = dest_dir or config.BACKUP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"estudos-{_timestamp()}.db"

    source = sqlite3.connect(config.DATABASE_PATH)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()

    _apply_retention(dest_dir)
    return dest_path


def _apply_retention(dest_dir: Path) -> None:
    backups = sorted(dest_dir.glob("estudos-*.db"), key=lambda p: p.name, reverse=True)
    for stale in backups[config.BACKUP_RETENTION :]:
        stale.unlink()


@dataclass
class BackupSummary:
    path: Path
    subjects_count: int
    size_bytes: int


def summarize(path: Path) -> BackupSummary:
    conn = sqlite3.connect(path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='subject'"
        )
        has_table = cursor.fetchone()[0] > 0
        count = 0
        if has_table:
            cursor.execute("SELECT COUNT(*) FROM subject")
            count = cursor.fetchone()[0]
    finally:
        conn.close()
    return BackupSummary(path=path, subjects_count=count, size_bytes=path.stat().st_size)


def restore_from(backup_path: Path) -> Path:
    """Restaura `backup_path` por cima do banco atual.

    Faz uma cópia de segurança do estado atual antes de sobrescrever (dá pra voltar
    atrás), fecha o pool de conexões, troca o arquivo, migra o schema e reabre.
    Chamado dentro de `db.maintenance_mode()` pela rota que expõe isso na UI.
    """
    safety_copy = create_backup(config.BACKUP_DIR / "pre-restore")
    with db.maintenance_mode():
        shutil.copyfile(backup_path, config.DATABASE_PATH)
        for suffix in ("-wal", "-shm"):
            stale = Path(str(config.DATABASE_PATH) + suffix)
            if stale.exists():
                stale.unlink()
        _run_migrations()
    return safety_copy


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    server_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(server_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(server_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.DATABASE_PATH}")
    command.upgrade(alembic_cfg, "head")
