"""fase 8: guia de aula (transcricao organizada por prompt simples)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("guia_md", sa.Text, nullable=True))
    op.add_column("lesson", sa.Column("guia_gerado_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("lesson", "guia_gerado_em")
    op.drop_column("lesson", "guia_md")
