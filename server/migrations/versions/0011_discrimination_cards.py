"""fase 8b: cards de discriminacao (pares confundiveis) na mesma tabela de cards

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("card_proposal", sa.Column("tipo", sa.String, nullable=False, server_default="flashcard"))
    op.add_column("card_proposal", sa.Column("termo_a", sa.String, nullable=True))
    op.add_column("card_proposal", sa.Column("termo_b", sa.String, nullable=True))
    op.add_column("card_proposal", sa.Column("eixo_distincao", sa.Text, nullable=True))
    op.add_column("card_proposal", sa.Column("start_s_a", sa.Float, nullable=True))
    op.add_column("card_proposal", sa.Column("end_s_a", sa.Float, nullable=True))
    op.add_column("card_proposal", sa.Column("start_s_b", sa.Float, nullable=True))
    op.add_column("card_proposal", sa.Column("end_s_b", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("card_proposal", "end_s_b")
    op.drop_column("card_proposal", "start_s_b")
    op.drop_column("card_proposal", "end_s_a")
    op.drop_column("card_proposal", "start_s_a")
    op.drop_column("card_proposal", "eixo_distincao")
    op.drop_column("card_proposal", "termo_b")
    op.drop_column("card_proposal", "termo_a")
    op.drop_column("card_proposal", "tipo")
