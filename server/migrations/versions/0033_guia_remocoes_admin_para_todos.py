"""Dominar o guia: questões que um admin já tinha removido da própria fila
passam a valer como removidas pra todos (pedido do usuário, junto com a
mudança em study/guia_scheduler.py::remover_exercicio, que faz isso daqui
pra frente).

Só dado, sem schema: toda questão ainda `aceito` com um registro em
`guia_exercicio_removido` de um usuário admin vira `descartado` -- o mesmo
status da tela de aprovação, que todas as filas já filtram. O registro de
remoção do admin fica: é por ele que a questão continua na lista de
removidas do admin, com o "desfazer" que a devolve pra todos.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE guia_exercicio
        SET status = 'descartado'
        WHERE status = 'aceito'
          AND id IN (
            SELECT r.exercicio_id
            FROM guia_exercicio_removido r
            JOIN "user" u ON u.id = r.user_id
            WHERE u.papel = 'admin'
          )
        """
    )


def downgrade() -> None:
    # Sem volta automática: depois do upgrade não dá pra distinguir o que
    # esta migração descartou do que foi descartado na aprovação ou pelo
    # "remover" novo -- reverter por palpite reaceitaria questão ruim. O
    # "desfazer" do admin, questão a questão, é o caminho de volta.
    pass
