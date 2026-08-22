"""fase 11: glossario (term, term_alias, definition, term_pin)

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "term",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String, nullable=False),
        sa.Column("rotulo", sa.String, nullable=False),
        sa.Column("destacar", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_term_slug", "term", ["slug"], unique=True)

    op.create_table(
        "term_alias",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("term_id", sa.Integer, sa.ForeignKey("term.id"), nullable=False),
        sa.Column("alias", sa.String, nullable=False),
    )
    op.create_index("ix_term_alias_alias", "term_alias", ["alias"], unique=True)
    op.create_index("ix_term_alias_term_id", "term_alias", ["term_id"])

    op.create_table(
        "definition",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("term_id", sa.Integer, sa.ForeignKey("term.id"), nullable=True),
        sa.Column("termo_proposto", sa.String, nullable=True),
        sa.Column("variantes_propostas_json", sa.Text, nullable=True),
        sa.Column("deriv_key", sa.String, nullable=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=True),
        sa.Column("material_id", sa.Integer, sa.ForeignKey("material.id"), nullable=True),
        sa.Column("start_s", sa.Float, nullable=True),
        sa.Column("pagina", sa.Integer, nullable=True),
        sa.Column("definicao_md", sa.Text, nullable=False),
        sa.Column("citacao_literal", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="proposto"),
        sa.Column("origem", sa.String, nullable=False, server_default="ia"),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("versao_nova_json", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_definition_term_id", "definition", ["term_id"])
    op.create_index("ix_definition_lesson_id", "definition", ["lesson_id"])

    op.create_table(
        "term_pin",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("term_id", sa.Integer, sa.ForeignKey("term.id"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("definition_id", sa.Integer, sa.ForeignKey("definition.id"), nullable=False),
    )
    op.create_index("ix_term_pin_term_subject", "term_pin", ["term_id", "subject_id"], unique=True)


def downgrade() -> None:
    op.drop_table("term_pin")
    op.drop_table("definition")
    op.drop_table("term_alias")
    op.drop_table("term")
