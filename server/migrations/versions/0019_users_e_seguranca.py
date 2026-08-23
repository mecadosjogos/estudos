"""usuários: login por usuário+senha, cadastro com aprovação, acesso
temporário (PLANO.md, seção "Acesso" -- o "Convite" adiado pro pós-v1)

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String, nullable=False, unique=True),
        sa.Column("senha_hash", sa.String, nullable=False),
        sa.Column("papel", sa.String, nullable=False, server_default="usuario"),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aprovado_por_id", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decidido_em", sa.DateTime(timezone=True), nullable=True),
    )

    from datetime import datetime, timezone

    from app.security import hash_password

    user_table = sa.table(
        "user",
        sa.column("username", sa.String),
        sa.column("senha_hash", sa.String),
        sa.column("papel", sa.String),
        sa.column("status", sa.String),
        sa.column("criado_em", sa.DateTime(timezone=True)),
        sa.column("decidido_em", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        user_table,
        [
            {
                "username": "admin",
                "senha_hash": hash_password("admin"),
                "papel": "admin",
                "status": "aprovado",
                "criado_em": now,
                "decidido_em": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("user")
