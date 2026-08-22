"""fase 12: busca unificada -- FTS5 sobre materiais, páginas de obra,
observações e definições, ao lado da transcrição (fase 5)

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Diferente de transcript_segment (fase 5, só INSERT/DELETE -- um segmento
# nunca é editado no lugar, reprocessar apaga e recria), as quatro fontes
# novas SÃO editadas com o registro vivo (conteudo_md ressincroniza, texto
# de página é corrigido à mão, observação é escrita, definição é editada) --
# por isso cada uma ganha também um trigger AFTER UPDATE, no padrão-livro do
# SQLite pra FTS5 de conteúdo externo (delete a linha velha, insere a nova).
_TABLES = [
    # (fts_table, source_table, column)
    ("material_fts", "material", "conteudo_md"),
    ("material_page_fts", "material_page", "texto"),
    ("edited_block_observacao_fts", "edited_block", "observacao"),
    ("definition_fts", "definition", "definicao_md"),
]


def upgrade() -> None:
    for fts_table, source_table, column in _TABLES:
        op.execute(
            f"""
            CREATE VIRTUAL TABLE {fts_table} USING fts5(
                {column},
                content='{source_table}',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {source_table}_search_ai AFTER INSERT ON {source_table} BEGIN
                INSERT INTO {fts_table}(rowid, {column}) VALUES (new.id, new.{column});
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {source_table}_search_ad AFTER DELETE ON {source_table} BEGIN
                INSERT INTO {fts_table}({fts_table}, rowid, {column}) VALUES ('delete', old.id, old.{column});
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {source_table}_search_au AFTER UPDATE ON {source_table} BEGIN
                INSERT INTO {fts_table}({fts_table}, rowid, {column}) VALUES ('delete', old.id, old.{column});
                INSERT INTO {fts_table}(rowid, {column}) VALUES (new.id, new.{column});
            END
            """
        )
        # Backfill: linhas de material/definition/etc. já existiam antes
        # desta migração -- os triggers só cobrem INSERT/UPDATE/DELETE
        # daqui pra frente, sem isto o índice nasceria vazio pro que já
        # estava no banco.
        op.execute(f"INSERT INTO {fts_table}(rowid, {column}) SELECT id, {column} FROM {source_table}")


def downgrade() -> None:
    for fts_table, source_table, _column in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {source_table}_search_au")
        op.execute(f"DROP TRIGGER IF EXISTS {source_table}_search_ad")
        op.execute(f"DROP TRIGGER IF EXISTS {source_table}_search_ai")
        op.execute(f"DROP TABLE IF EXISTS {fts_table}")
