"""fase 8: revisao humana da transcricao (confianca, edicao, aprovacao)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transcript", sa.Column("aprovado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transcript_segment", sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("transcript_segment", "editado_em")
    op.drop_column("transcript", "aprovado_em")
