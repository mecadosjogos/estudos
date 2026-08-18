"""fase 7: revisao espacada (SM-2), calibracao

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("card_proposal", sa.Column("ease_factor", sa.Float, nullable=False, server_default="2.5"))
    op.add_column("card_proposal", sa.Column("interval_days", sa.Integer, nullable=False, server_default="0"))
    op.add_column("card_proposal", sa.Column("repetitions", sa.Integer, nullable=False, server_default="0"))
    op.add_column("card_proposal", sa.Column("due_date", sa.Date, nullable=True))
    op.add_column("card_proposal", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_card_proposal_status_due", "card_proposal", ["status", "due_date"])

    op.create_table(
        "review_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("card_id", sa.Integer, sa.ForeignKey("card_proposal.id"), nullable=False),
        sa.Column("confianca", sa.String, nullable=False),
        sa.Column("qualidade", sa.Integer, nullable=False),
        sa.Column("acertou", sa.Boolean, nullable=False),
        sa.Column("revisado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_log_card_id", "review_log", ["card_id"])
    op.create_index("ix_review_log_revisado_em", "review_log", ["revisado_em"])


def downgrade() -> None:
    op.drop_table("review_log")
    op.drop_index("ix_card_proposal_status_due", table_name="card_proposal")
    op.drop_column("card_proposal", "last_reviewed_at")
    op.drop_column("card_proposal", "due_date")
    op.drop_column("card_proposal", "repetitions")
    op.drop_column("card_proposal", "interval_days")
    op.drop_column("card_proposal", "ease_factor")
