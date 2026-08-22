"""fase 15: mapa de taxonomia (Lesson.mapa_mermaid)

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("mapa_mermaid", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("lesson", "mapa_mermaid")
