"""narração do guia vira um mp3 só por aula (não um por seção) -- GuiaSecao
ganha audio_start_s/audio_end_s marcando a posição de cada seção nesse
áudio único, mesmo padrão de TranscriptSegment.start_s/end_s. Puramente
aditivo -- nada lê/escreve ainda.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("guia_secao", sa.Column("audio_start_s", sa.Float, nullable=True))
    op.add_column("guia_secao", sa.Column("audio_end_s", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("guia_secao", "audio_end_s")
    op.drop_column("guia_secao", "audio_start_s")
