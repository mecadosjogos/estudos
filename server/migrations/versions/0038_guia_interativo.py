"""Guia interativo: o que a skill /guia-interativo escreve para a página
interativa de uma consolidação ou guia focado (resumos dos exemplos,
visuais, seções de fora, correções do mapa e dos artigos). Uma linha por
aula, substituída por inteiro a cada envio.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guia_interativo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False, unique=True),
        sa.Column("conteudo_json", sa.Text, nullable=False),
        sa.Column("gerado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("guia_interativo")
