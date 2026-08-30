"""narração em áudio do guia de aula: coluna de versão pra saber se o áudio
gerado (TTS local via GPU, tts-service/) está desatualizado em relação ao
guia estruturado. Puramente aditivo -- nada lê/escreve ainda.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("guia_audio_gerado_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("lesson", "guia_audio_gerado_em")
