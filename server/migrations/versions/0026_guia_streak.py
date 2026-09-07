"""Efeito multiplicador de sequência (streak) em "Dominar o guia": duas
colunas de contador -- uma por aula (tamanho da mesa) e uma por exercício
(salto de caixa Leitner) -- ver study/guia_scheduler.py.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lesson", sa.Column("guia_progresso_streak_atual", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column(
        "guia_exercicio", sa.Column("streak_atual", sa.Integer, nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("guia_exercicio", "streak_atual")
    op.drop_column("lesson", "guia_progresso_streak_atual")
