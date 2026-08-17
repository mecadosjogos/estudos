"""fase 2: tabela lesson + cor das matérias do seed

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lesson",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("data", sa.Date, nullable=False),
        sa.Column("google_doc_url", sa.String, nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
    )

    from app.seed_data import SUBJECTS

    connection = op.get_bind()
    subject_table = sa.table(
        "subject", sa.column("sigla", sa.String), sa.column("cor", sa.String)
    )
    for s in SUBJECTS:
        connection.execute(
            subject_table.update()
            .where(subject_table.c.sigla == s["sigla"])
            .values(cor=s["cor"])
        )


def downgrade() -> None:
    op.drop_table("lesson")
