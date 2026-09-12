""""Dominar o guia": filtro de tipos de exercício por usuário+aula --
guarda os tipos DESLIGADOS (JSON), pra que o padrão nulo signifique
"todos ligados" e um tipo novo entre na fila sozinho.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("guia_lesson_progresso", sa.Column("tipos_desativados", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("guia_lesson_progresso", "tipos_desativados")
