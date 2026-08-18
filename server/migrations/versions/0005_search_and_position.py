"""fase 5: busca FTS5 sobre a transcrição + posição salva do player

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("posicao_s", sa.Float, nullable=False, server_default="0"))

    # content='transcript_segment': a FTS5 não duplica o texto, só indexa —
    # a tabela de origem continua sendo a única fonte de verdade.
    op.execute(
        """
        CREATE VIRTUAL TABLE transcript_fts USING fts5(
            text,
            content='transcript_segment',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )

    # Reindexar é apagar-e-regravar (Integridade #2 do PLANO.md): reprocessar
    # uma aula deleta os segmentos antigos e insere os novos, então os
    # triggers de INSERT/DELETE bastam — nunca há UPDATE de segmento.
    op.execute(
        """
        CREATE TRIGGER transcript_segment_ai AFTER INSERT ON transcript_segment BEGIN
            INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER transcript_segment_ad AFTER DELETE ON transcript_segment BEGIN
            INSERT INTO transcript_fts(transcript_fts, rowid, text) VALUES ('delete', old.id, old.text);
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS transcript_segment_ad")
    op.execute("DROP TRIGGER IF EXISTS transcript_segment_ai")
    op.execute("DROP TABLE IF EXISTS transcript_fts")
    op.drop_column("lesson", "posicao_s")
