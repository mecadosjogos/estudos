"""Exercícios de memorização derivados do guia de aula ("Dominar o
guia") -- sistema deliberadamente separado de card_proposal/SM-2 (ver
PLANO.md): fonte é o guia_md, não a transcrição. Duas tabelas novas
(guia_exercicio, guia_exercicio_tentativa) e duas colunas de estado do
algoritmo posicional em lesson.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lesson", sa.Column("guia_progresso_posicao_atual", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column(
        "lesson", sa.Column("guia_progresso_mesa_tamanho", sa.Integer, nullable=False, server_default="10")
    )

    op.create_table(
        "guia_exercicio",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("tipo", sa.String, nullable=False),
        sa.Column("secao_titulo", sa.String, nullable=True),
        sa.Column("pergunta", sa.Text, nullable=False),
        sa.Column("gabarito_json", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("versao_nova_json", sa.Text, nullable=True),
        sa.Column("caixa", sa.Integer, nullable=False, server_default="0"),
        sa.Column("na_mesa", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("posicao_alvo", sa.Integer, nullable=True),
        sa.Column("dominado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guia_exercicio_lesson_id", "guia_exercicio", ["lesson_id"])
    op.create_index("ix_guia_exercicio_na_mesa_posicao", "guia_exercicio", ["na_mesa", "posicao_alvo"])

    op.create_table(
        "guia_exercicio_tentativa",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("exercicio_id", sa.Integer, sa.ForeignKey("guia_exercicio.id"), nullable=False),
        sa.Column("resposta_texto", sa.Text, nullable=True),
        sa.Column("grau_acerto", sa.Float, nullable=False),
        sa.Column("confianca", sa.String, nullable=True),
        sa.Column("respondido_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guia_exercicio_tentativa_exercicio_id", "guia_exercicio_tentativa", ["exercicio_id"])


def downgrade() -> None:
    op.drop_index("ix_guia_exercicio_tentativa_exercicio_id", table_name="guia_exercicio_tentativa")
    op.drop_table("guia_exercicio_tentativa")
    op.drop_index("ix_guia_exercicio_na_mesa_posicao", table_name="guia_exercicio")
    op.drop_index("ix_guia_exercicio_lesson_id", table_name="guia_exercicio")
    op.drop_table("guia_exercicio")
    op.drop_column("lesson", "guia_progresso_mesa_tamanho")
    op.drop_column("lesson", "guia_progresso_posicao_atual")
