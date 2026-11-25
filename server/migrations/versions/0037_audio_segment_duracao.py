"""Duração de cada gravação original (`audio_segment.duracao_s`).

Na VPS só fica o mp3 da aula inteira, com as gravações já concatenadas, e
os originais são apagados depois da transcrição -- sem a duração de cada
uma, não dá pra saber onde a parte 1 termina e a 2 começa. Usado pela
exportação de áudios do admin (export/audio_zip.py). Nulo nas aulas
anteriores a esta migração: a exportação estima o corte pelo tamanho
dos originais.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audio_segment", sa.Column("duracao_s", sa.Float, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audio_segment") as batch:
        batch.drop_column("duracao_s")
