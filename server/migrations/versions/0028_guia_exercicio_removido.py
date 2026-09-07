"""Remoção de questão por usuário em "Dominar o guia" -- tabela
`guia_exercicio_removido`, uma linha por (usuário, exercício).

Tabela separada, e não uma coluna em `guia_exercicio_progresso`, porque o
usuário pediu que a remoção SOBREVIVA ao "limpar progresso" -- e limpar
progresso apaga as linhas de progresso inteiras. Também não é
`guia_exercicio.status='descartado'`: aquilo é compartilhado entre todos
os usuários, isto é a fila de uma pessoa só.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guia_exercicio_removido",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("exercicio_id", sa.Integer, sa.ForeignKey("guia_exercicio.id"), nullable=False),
        sa.Column("removido_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_guia_exercicio_removido_user_exercicio",
        "guia_exercicio_removido",
        ["user_id", "exercicio_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_guia_exercicio_removido_user_exercicio", table_name="guia_exercicio_removido")
    op.drop_table("guia_exercicio_removido")
