"""Conexão SQLite. WAL + busy_timeout desde o primeiro dia (Integridade #1 do PLANO.md).

O engine fica atrás de um holder porque a restauração precisa fechar todo o pool
de conexões antes de trocar o arquivo do banco e reabrir depois — trocar o arquivo
sob uma conexão viva corrompe o WAL (ver PLANO.md, Limites operacionais).
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from . import config


class EngineHolder:
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.maintenance_mode = False
        self._build()

    def _build(self):
        self.engine = create_engine(
            f"sqlite:///{config.DATABASE_PATH}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def _set_pragmas(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={config.BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def close(self):
        """Fecha todas as conexões do pool. Chamado antes de restaurar o banco."""
        if self.engine is not None:
            self.engine.dispose()

    def reopen(self):
        """Recria o engine depois de o arquivo do banco ter sido trocado."""
        self._build()


holder = EngineHolder()


def get_session():
    if holder.maintenance_mode:
        raise RuntimeError("Sistema em modo manutenção — restauração em andamento")
    session = holder.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def maintenance_mode():
    """Fecha o pool de conexões, executa o bloco, reabre o pool ao final.

    Usado pela restauração: trocar o arquivo SQLite com conexões vivas (WAL +
    shared memory ativos) corrompe o banco.
    """
    holder.maintenance_mode = True
    holder.close()
    try:
        yield
    finally:
        holder.reopen()
        holder.maintenance_mode = False
