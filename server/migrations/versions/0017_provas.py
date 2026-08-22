"""fase 14: ementa (opcional), provas e escopo por assunto

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ementa",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ementa_subject_id", "ementa", ["subject_id"], unique=True)

    op.create_table(
        "ementa_topico",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ementa_id", sa.Integer, sa.ForeignKey("ementa.id"), nullable=False),
        sa.Column("assunto_id", sa.Integer, sa.ForeignKey("assunto.id"), nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
    )
    op.create_index("ix_ementa_topico_ementa_id", "ementa_topico", ["ementa_id"])

    op.create_table(
        "exam",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("data", sa.Date, nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_exam_subject_id", "exam", ["subject_id"])

    op.create_table(
        "exam_scope",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("exam_id", sa.Integer, sa.ForeignKey("exam.id"), nullable=False),
        sa.Column("assunto_id", sa.Integer, sa.ForeignKey("assunto.id"), nullable=False),
    )
    op.create_index("ix_exam_scope_exam_assunto", "exam_scope", ["exam_id", "assunto_id"], unique=True)


def downgrade() -> None:
    op.drop_table("exam_scope")
    op.drop_table("exam")
    op.drop_table("ementa_topico")
    op.drop_table("ementa")
