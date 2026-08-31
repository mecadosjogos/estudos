"""Lesson ganha material_aula_texto -- texto colado à mão (lousa, anotações
dadas em aula), fonte primária como o áudio, fora dele. Puramente aditivo,
nullable, sem backfill.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("material_aula_texto", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("lesson", "material_aula_texto")
