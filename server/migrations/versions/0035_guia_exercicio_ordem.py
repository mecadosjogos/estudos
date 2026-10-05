"""Ordem de conteúdo dos exercícios do "Dominar o guia".

`guia_exercicio.ordem` é a posição do exercício no índice do guia
(study/guia_ordem.py) e passa a ser a ordem em que o backlog entra na
mesa -- antes era `criado_em`, ou seja, a ordem do lote da IA, que numa
aula veio agrupada por tipo (todas as definições, depois todas as
lacunas...).

Só cria a coluna: o preenchimento é `python scripts/reordenar_exercicios_guia.py`
(ou POST /lessons/{id}/guia/exercicios-reordenar). Enquanto estiver nula,
a fila cai no `criado_em` de antes.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("guia_exercicio") as batch_op:
        batch_op.add_column(sa.Column("ordem", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("guia_exercicio") as batch_op:
        batch_op.drop_column("ordem")
