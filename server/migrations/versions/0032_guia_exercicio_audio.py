"""Locução do "Dominar o guia" -- áudio da pergunta e da resposta de cada
exercício, narrado pelo TTS local (tts-service/, alvo `tts_exercicios`).

`audio_pergunta_hash`/`audio_resposta_hash` guardam o hash do texto falado
que gerou o mp3 em disco: o áudio só vale enquanto bate com o hash do texto
atual (study/guia_locucao.py), então editar a questão ou mudar a regra de
fala invalida sozinho, sem job de limpeza.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("guia_exercicio") as batch_op:
        batch_op.add_column(sa.Column("audio_pergunta_hash", sa.String, nullable=True))
        batch_op.add_column(sa.Column("audio_resposta_hash", sa.String, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("guia_exercicio") as batch_op:
        batch_op.drop_column("audio_resposta_hash")
        batch_op.drop_column("audio_pergunta_hash")
