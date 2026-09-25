"""Fase 13b -- resposta certa e fila visível das dissertativas.

- `dissertativa_question.resposta_modelo`: a resposta certa, gerada junto
  com a questão (diferente da "versão melhorada", que reescreve a resposta
  de quem respondeu); `origem`: "local:<modelo>" ou "claude".
- `dissertativa_attempt.resposta_certa_vista_em` (abrir antes de reescrever
  conta como desistência) e `avaliacao_vista_em` (a fila da tela mostra
  "corrigida — ver avaliação" até a pessoa abrir).

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dissertativa_question") as batch_op:
        batch_op.add_column(sa.Column("resposta_modelo", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("origem", sa.String, nullable=True))
    with op.batch_alter_table("dissertativa_attempt") as batch_op:
        batch_op.add_column(sa.Column("resposta_certa_vista_em", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("avaliacao_vista_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dissertativa_attempt") as batch_op:
        batch_op.drop_column("avaliacao_vista_em")
        batch_op.drop_column("resposta_certa_vista_em")
    with op.batch_alter_table("dissertativa_question") as batch_op:
        batch_op.drop_column("origem")
        batch_op.drop_column("resposta_modelo")
