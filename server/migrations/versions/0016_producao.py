"""fase 13: produção -- Feynman por voz e dissertativa avaliada

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feynman_attempt",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("term_id", sa.Integer, sa.ForeignKey("term.id"), nullable=False),
        sa.Column("audio_path", sa.String, nullable=False),
        sa.Column("transcript_text", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="transcrito"),
        sa.Column("pontos_cobertos_json", sa.Text, nullable=True),
        sa.Column("pontos_faltantes_json", sa.Text, nullable=True),
        sa.Column("divergencias_json", sa.Text, nullable=True),
        sa.Column("comentario_geral", sa.Text, nullable=True),
        sa.Column("erro", sa.Text, nullable=True),
        sa.Column("ai_call_id", sa.Integer, sa.ForeignKey("ai_call.id"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("avaliado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_feynman_attempt_term_id", "feynman_attempt", ["term_id"])

    op.create_table(
        "dissertativa_question",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=True),
        sa.Column("assunto_id", sa.Integer, sa.ForeignKey("assunto.id"), nullable=True),
        sa.Column("enunciado", sa.Text, nullable=False),
        sa.Column("rubrica_json", sa.Text, nullable=False),
        sa.Column("ai_call_id", sa.Integer, sa.ForeignKey("ai_call.id"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dissertativa_question_subject_id", "dissertativa_question", ["subject_id"])

    op.create_table(
        "dissertativa_attempt",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("dissertativa_question.id"), nullable=False),
        sa.Column("resposta_texto", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="respondido"),
        sa.Column("pontos_cobertos_json", sa.Text, nullable=True),
        sa.Column("pontos_faltantes_json", sa.Text, nullable=True),
        sa.Column("comentario", sa.Text, nullable=True),
        sa.Column("ai_call_id", sa.Integer, sa.ForeignKey("ai_call.id"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("avaliado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dissertativa_attempt_question_id", "dissertativa_attempt", ["question_id"])


def downgrade() -> None:
    op.drop_table("dissertativa_attempt")
    op.drop_table("dissertativa_question")
    op.drop_table("feynman_attempt")
