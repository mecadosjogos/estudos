"""Progresso de "Dominar o guia" por usuário -- estado de agendamento
(caixa, streak, mesa, posição) sai de `lesson`/`guia_exercicio` e vira
duas tabelas novas (`guia_lesson_progresso`, `guia_exercicio_progresso`),
uma linha por (usuário, aula)/(usuário, exercício). Pedido explícito do
usuário: o sistema virou multiusuário (fase 19) mas "Dominar o guia"
ainda misturava o progresso de todo mundo numa aula só.

`guia_exercicio_tentativa` ganha `user_id` pelo mesmo motivo -- o
histórico de respostas também é por pessoa.

Dados existentes são migrados pro usuário "admin" (único usuário até
agora) em vez de descartados.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guia_lesson_progresso",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("posicao_atual", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mesa_tamanho", sa.Integer, nullable=False, server_default="5"),
        sa.Column("streak_atual", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_guia_lesson_progresso_user_lesson", "guia_lesson_progresso", ["user_id", "lesson_id"], unique=True
    )

    op.create_table(
        "guia_exercicio_progresso",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("exercicio_id", sa.Integer, sa.ForeignKey("guia_exercicio.id"), nullable=False),
        sa.Column("caixa", sa.Integer, nullable=False, server_default="0"),
        sa.Column("streak_atual", sa.Integer, nullable=False, server_default="0"),
        sa.Column("na_mesa", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("posicao_alvo", sa.Integer, nullable=True),
        sa.Column("dominado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_guia_exercicio_progresso_user_exercicio",
        "guia_exercicio_progresso",
        ["user_id", "exercicio_id"],
        unique=True,
    )
    op.create_index(
        "ix_guia_exercicio_progresso_na_mesa_posicao", "guia_exercicio_progresso", ["na_mesa", "posicao_alvo"]
    )

    conn = op.get_bind()
    admin_id = conn.execute(sa.text("SELECT id FROM user WHERE username = 'admin'")).scalar()

    if admin_id is not None:
        conn.execute(
            sa.text(
                "INSERT INTO guia_lesson_progresso (user_id, lesson_id, posicao_atual, mesa_tamanho, streak_atual) "
                "SELECT :uid, id, guia_progresso_posicao_atual, guia_progresso_mesa_tamanho, guia_progresso_streak_atual "
                "FROM lesson WHERE guia_titulo IS NOT NULL"
            ),
            {"uid": admin_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO guia_exercicio_progresso "
                "(user_id, exercicio_id, caixa, streak_atual, na_mesa, posicao_alvo, dominado_em, last_reviewed_at) "
                "SELECT :uid, id, caixa, streak_atual, na_mesa, posicao_alvo, dominado_em, last_reviewed_at "
                "FROM guia_exercicio"
            ),
            {"uid": admin_id},
        )

    with op.batch_alter_table("guia_exercicio_tentativa") as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("user.id", name="fk_guia_exercicio_tentativa_user_id"),
                nullable=True,
            )
        )
    if admin_id is not None:
        conn.execute(sa.text("UPDATE guia_exercicio_tentativa SET user_id = :uid"), {"uid": admin_id})
    with op.batch_alter_table("guia_exercicio_tentativa") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer, nullable=False)
    op.create_index("ix_guia_exercicio_tentativa_user_id", "guia_exercicio_tentativa", ["user_id"])

    op.drop_index("ix_guia_exercicio_na_mesa_posicao", table_name="guia_exercicio")
    with op.batch_alter_table("guia_exercicio") as batch_op:
        batch_op.drop_column("caixa")
        batch_op.drop_column("streak_atual")
        batch_op.drop_column("na_mesa")
        batch_op.drop_column("posicao_alvo")
        batch_op.drop_column("dominado_em")
        batch_op.drop_column("last_reviewed_at")

    with op.batch_alter_table("lesson") as batch_op:
        batch_op.drop_column("guia_progresso_posicao_atual")
        batch_op.drop_column("guia_progresso_mesa_tamanho")
        batch_op.drop_column("guia_progresso_streak_atual")


def downgrade() -> None:
    with op.batch_alter_table("lesson") as batch_op:
        batch_op.add_column(sa.Column("guia_progresso_posicao_atual", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("guia_progresso_mesa_tamanho", sa.Integer, nullable=False, server_default="5"))
        batch_op.add_column(sa.Column("guia_progresso_streak_atual", sa.Integer, nullable=False, server_default="0"))

    with op.batch_alter_table("guia_exercicio") as batch_op:
        batch_op.add_column(sa.Column("caixa", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("streak_atual", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("na_mesa", sa.Boolean, nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("posicao_alvo", sa.Integer, nullable=True))
        batch_op.add_column(sa.Column("dominado_em", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_guia_exercicio_na_mesa_posicao", "guia_exercicio", ["na_mesa", "posicao_alvo"])

    op.drop_index("ix_guia_exercicio_tentativa_user_id", table_name="guia_exercicio_tentativa")
    with op.batch_alter_table("guia_exercicio_tentativa") as batch_op:
        batch_op.drop_column("user_id")

    op.drop_index("ix_guia_exercicio_progresso_na_mesa_posicao", table_name="guia_exercicio_progresso")
    op.drop_index("ix_guia_exercicio_progresso_user_exercicio", table_name="guia_exercicio_progresso")
    op.drop_table("guia_exercicio_progresso")

    op.drop_index("ix_guia_lesson_progresso_user_lesson", table_name="guia_lesson_progresso")
    op.drop_table("guia_lesson_progresso")
