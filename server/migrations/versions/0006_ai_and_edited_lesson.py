"""fase 6: IA, aula editada e ponte manual

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson", sa.Column("resumo", sa.Text, nullable=True))

    op.create_table(
        "edited_block",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("tipo", sa.String, nullable=False, server_default="normal"),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("end_s", sa.Float, nullable=False),
        sa.Column("origens_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("repeticoes", sa.Integer, nullable=False, server_default="1"),
        sa.Column("baixa_confianca", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("confirmado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observacao", sa.Text, nullable=True),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("versao_nova_json", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_edited_block_lesson_deriv", "edited_block", ["lesson_id", "deriv_key"])

    op.create_table(
        "card_proposal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("frente", sa.Text, nullable=False),
        sa.Column("verso", sa.Text, nullable=False),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("end_s", sa.Float, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("versao_nova_json", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_card_proposal_lesson_deriv", "card_proposal", ["lesson_id", "deriv_key"])

    op.create_table(
        "announcement_proposal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("data_anunciada", sa.Date, nullable=True),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_announcement_proposal_lesson_deriv", "announcement_proposal", ["lesson_id", "deriv_key"]
    )

    op.create_table(
        "outline_item",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("end_s", sa.Float, nullable=False),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outline_item_lesson_deriv", "outline_item", ["lesson_id", "deriv_key"])

    op.create_table(
        "article_mention",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("deriv_key", sa.String, nullable=False),
        sa.Column("texto_citado", sa.String, nullable=False),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("baixa_confianca", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("confirmado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orfao_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_article_mention_lesson_deriv", "article_mention", ["lesson_id", "deriv_key"])

    op.create_table(
        "ai_call",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=True),
        sa.Column("tipo_acao", sa.String, nullable=False),
        sa.Column("via", sa.String, nullable=False, server_default="automatico"),
        sa.Column("modelo", sa.String, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("custo_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("raw_response_json", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_call_criado_em", "ai_call", ["criado_em"])


def downgrade() -> None:
    op.drop_table("ai_call")
    op.drop_table("article_mention")
    op.drop_table("outline_item")
    op.drop_table("announcement_proposal")
    op.drop_table("card_proposal")
    op.drop_table("edited_block")
    op.drop_column("lesson", "resumo")
