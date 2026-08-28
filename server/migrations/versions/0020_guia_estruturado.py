"""guia de aula estruturado: título/árvore/seções/sumário em campos e
tabelas próprias em vez de um markdown único (PLANO.md). Puramente
aditivo -- guia_md/guia_gerado_em continuam existindo como cache, nada
aqui é lido/escrito ainda pelo código existente.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("guia_titulo", sa.String, nullable=True))
    op.add_column("lesson", sa.Column("guia_arvore_json", sa.Text, nullable=True))
    op.add_column("lesson", sa.Column("guia_trechos_incompletos_json", sa.Text, nullable=True))

    op.create_table(
        "guia_secao",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("corpo", sa.Text, nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guia_secao_lesson", "guia_secao", ["lesson_id"])

    op.create_table(
        "guia_topico",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("secao_alvo_slug", sa.String, nullable=True),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("versao_nova_json", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guia_topico_lesson_deriv", "guia_topico", ["lesson_id", "deriv_key"])


def downgrade() -> None:
    op.drop_table("guia_topico")
    op.drop_table("guia_secao")
    op.drop_column("lesson", "guia_trechos_incompletos_json")
    op.drop_column("lesson", "guia_arvore_json")
    op.drop_column("lesson", "guia_titulo")
