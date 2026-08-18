"""fase 8: assuntos (global, cobertura por materia, proposta por aula)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assunto",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String, nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("descricao", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assunto_slug", "assunto", ["slug"], unique=True)

    op.create_table(
        "assunto_cobertura",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("assunto_id", sa.Integer, sa.ForeignKey("assunto.id"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="dado"),
        sa.Column("origem", sa.String, nullable=False, server_default="ia"),
        sa.Column("ordem", sa.Integer, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assunto_cobertura_assunto_id", "assunto_cobertura", ["assunto_id"])
    op.create_index(
        "ix_assunto_cobertura_assunto_subject", "assunto_cobertura", ["assunto_id", "subject_id"], unique=True
    )

    op.create_table(
        "lesson_assunto",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("texto_proposto", sa.String, nullable=False),
        sa.Column("assunto_id", sa.Integer, sa.ForeignKey("assunto.id"), nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lesson_assunto_lesson_id", "lesson_assunto", ["lesson_id"])
    op.create_index("ix_lesson_assunto_assunto_id", "lesson_assunto", ["assunto_id"])


def downgrade() -> None:
    op.drop_table("lesson_assunto")
    op.drop_table("assunto_cobertura")
    op.drop_table("assunto")
