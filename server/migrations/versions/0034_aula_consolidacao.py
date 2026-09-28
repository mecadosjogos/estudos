"""Aula de consolidação: uma aula especial da matéria que junta os guias
de várias aulas num guia único, sem repetição e com índice hierárquico
próprio (PLANO.md, "Aula de consolidação"). Sem áudio nem transcrição --
o guia sai dos guias das aulas-fonte pela skill /consolidar-guia.

`tipo` discrimina aula normal de consolidação; `consolidacao_fontes_json`
guarda os ids das aulas-fonte em ordem cronológica (lista simples, não
tabela: a consolidação é feita uma vez, com a matéria fechada).

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("tipo", sa.String, nullable=False, server_default="aula"))
    op.add_column("lesson", sa.Column("consolidacao_fontes_json", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("lesson", "consolidacao_fontes_json")
    op.drop_column("lesson", "tipo")
