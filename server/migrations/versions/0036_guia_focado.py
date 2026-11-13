"""Guia "Focado": consolidação com foco (uma prova, um tema) -- ver
models.py::Lesson e ai/consolidacao.py.

`foco_orientacao` (o que o usuário passou, literal), `foco_md` (bloco
"Foco deste guia" escrito pela skill), `foco_marcas_json` (títulos
marcados como foco) e `exam_id` (prova cadastrada, opcional). Tudo
nulo numa aula ou consolidação comum -- nada muda no que já existe.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("foco_orientacao", sa.Text, nullable=True))
    op.add_column("lesson", sa.Column("foco_md", sa.Text, nullable=True))
    op.add_column("lesson", sa.Column("foco_marcas_json", sa.Text, nullable=True))
    # SQLite aceita REFERENCES inline num ADD COLUMN anulável; o batch
    # recriaria a tabela lesson inteira, referenciada por meio banco.
    op.execute("ALTER TABLE lesson ADD COLUMN exam_id INTEGER REFERENCES exam(id)")


def downgrade() -> None:
    # Coluna com FK: o SQLite não larga com DROP COLUMN, só recriando a tabela.
    with op.batch_alter_table("lesson") as batch:
        batch.drop_column("exam_id")
    op.drop_column("lesson", "foco_marcas_json")
    op.drop_column("lesson", "foco_md")
    op.drop_column("lesson", "foco_orientacao")
