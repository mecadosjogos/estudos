"""fundação: tabela subject + seed das 5 matérias do semestre

Revision ID: 0001
Revises:
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subject",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String, nullable=False),
        sa.Column("sigla", sa.String, nullable=False, unique=True),
        sa.Column("cor", sa.String, nullable=True),
        sa.Column("diploma_padrao", sa.String, nullable=True),
        sa.Column("continua_de_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=True),
        sa.Column("encerrada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
    )

    from datetime import datetime, timezone

    from app.seed_data import SUBJECTS

    subject_table = sa.table(
        "subject",
        sa.column("nome", sa.String),
        sa.column("sigla", sa.String),
        sa.column("diploma_padrao", sa.String),
        sa.column("criada_em", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        subject_table,
        [
            {
                "nome": s["nome"],
                "sigla": s["sigla"],
                "diploma_padrao": s["diploma_padrao"],
                "criada_em": datetime.now(timezone.utc),
            }
            for s in SUBJECTS
        ],
    )


def downgrade() -> None:
    op.drop_table("subject")
