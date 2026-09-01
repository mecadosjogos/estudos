"""Lesson ganha material_aula_url -- link do Google Doc de onde
material_aula_texto pode ser buscado automaticamente ("Buscar conteúdo"),
alternativa a colar o texto direto. Puramente aditivo, nullable.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("material_aula_url", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("lesson", "material_aula_url")
