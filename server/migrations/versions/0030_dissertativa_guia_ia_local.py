"""Fase 13b -- dissertativa pelo guia, corrigida pela IA local.

- `ia_local_job` / `ia_local_presenca`: fila que a máquina com GPU puxa
  por long-poll (a VPS nunca abre conexão com ela).
- `dissertativa_question` ganha fonte/tipo/critério/seções e a chave de
  derivação `guia_gerado_em_ref`; o que já existe fica `fonte="transcricao"`
  (legado, só leitura).
- `dissertativa_attempt` ganha dono (`user_id`, nulo no legado), confiança
  declarada antes do feedback, a cadeia de reescrita (v1 -> v2) e as saídas
  do juiz e do redator.
- `dissertativa_progresso` (espaçamento por usuário) e
  `dissertativa_discordancia` ("discordo" num veredito).

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dissertativa_question") as batch_op:
        batch_op.add_column(sa.Column("fonte", sa.String, nullable=False, server_default="transcricao"))
        batch_op.add_column(sa.Column("tipo", sa.String, nullable=True))
        batch_op.add_column(sa.Column("criterio_texto", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("secoes_json", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("guia_gerado_em_ref", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_dissertativa_question_lesson_id", "dissertativa_question", ["lesson_id"])

    with op.batch_alter_table("dissertativa_attempt") as batch_op:
        batch_op.add_column(
            sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", name="fk_dissertativa_attempt_user_id"), nullable=True)
        )
        batch_op.add_column(sa.Column("erro", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("confianca", sa.Integer, nullable=True))
        batch_op.add_column(sa.Column("autoavaliacao_texto", sa.Text, nullable=True))
        batch_op.add_column(
            sa.Column(
                "tentativa_anterior_id",
                sa.Integer,
                sa.ForeignKey("dissertativa_attempt.id", name="fk_dissertativa_attempt_anterior_id"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("sugestoes_escolhidas_json", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("vereditos_json", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("feedback_json", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("motor", sa.String, nullable=True))
        batch_op.add_column(sa.Column("modelo", sa.String, nullable=True))
        batch_op.add_column(sa.Column("segundos_total", sa.Float, nullable=True))
        batch_op.add_column(sa.Column("pistas_abertas_json", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("modelo_revelado_em", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("modelo_revelado_por_desistencia", sa.Boolean, nullable=False, server_default=sa.false())
        )
    op.create_index("ix_dissertativa_attempt_user_id", "dissertativa_attempt", ["user_id"])

    op.create_table(
        "dissertativa_progresso",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("dissertativa_question.id"), nullable=False),
        sa.Column("caixa", sa.Integer, nullable=False, server_default="0"),
        sa.Column("streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("proxima_revisao_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_cobertura", sa.Float, nullable=True),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "question_id", name="uq_dissertativa_progresso_user_question"),
    )
    op.create_index(
        "ix_dissertativa_progresso_user_revisao", "dissertativa_progresso", ["user_id", "proxima_revisao_em"]
    )

    op.create_table(
        "dissertativa_discordancia",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attempt_id", sa.Integer, sa.ForeignKey("dissertativa_attempt.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("ponto_idx", sa.Integer, nullable=False),
        sa.Column("veredito_modelo", sa.String, nullable=False),
        sa.Column("veredito_usuario", sa.String, nullable=False),
        sa.Column("comentario", sa.Text, nullable=True),
        sa.Column("modelo", sa.String, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dissertativa_discordancia_attempt_id", "dissertativa_discordancia", ["attempt_id"])

    op.create_table(
        "ia_local_job",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("dissertativa_question.id"), nullable=True),
        sa.Column("attempt_id", sa.Integer, sa.ForeignKey("dissertativa_attempt.id"), nullable=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("resultado_json", sa.Text, nullable=True),
        sa.Column("etapa", sa.String, nullable=True),
        sa.Column("palavras", sa.Integer, nullable=False, server_default="0"),
        sa.Column("claim_token", sa.String, nullable=True),
        sa.Column("claimed_by", sa.String, nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("erro", sa.Text, nullable=True),
        sa.Column("motor", sa.String, nullable=True),
        sa.Column("modelo", sa.String, nullable=True),
        sa.Column("segundos_total", sa.Float, nullable=True),
        sa.Column("tokens_por_s", sa.Float, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ia_local_job_status_criado", "ia_local_job", ["status", "criado_em"])
    op.create_index("ix_ia_local_job_attempt_id", "ia_local_job", ["attempt_id"])

    op.create_table(
        "ia_local_presenca",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("worker_name", sa.String, nullable=False, unique=True),
        sa.Column("visto_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motor", sa.String, nullable=True),
        sa.Column("modelo", sa.String, nullable=True),
        sa.Column("claude_autorizado_ate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocupado_etapa", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ia_local_presenca")
    op.drop_index("ix_ia_local_job_attempt_id", table_name="ia_local_job")
    op.drop_index("ix_ia_local_job_status_criado", table_name="ia_local_job")
    op.drop_table("ia_local_job")
    op.drop_index("ix_dissertativa_discordancia_attempt_id", table_name="dissertativa_discordancia")
    op.drop_table("dissertativa_discordancia")
    op.drop_index("ix_dissertativa_progresso_user_revisao", table_name="dissertativa_progresso")
    op.drop_table("dissertativa_progresso")

    op.drop_index("ix_dissertativa_attempt_user_id", table_name="dissertativa_attempt")
    with op.batch_alter_table("dissertativa_attempt") as batch_op:
        for coluna in (
            "modelo_revelado_por_desistencia", "modelo_revelado_em", "pistas_abertas_json", "segundos_total",
            "modelo", "motor", "feedback_json", "vereditos_json", "sugestoes_escolhidas_json",
            "tentativa_anterior_id", "autoavaliacao_texto", "confianca", "erro", "user_id",
        ):
            batch_op.drop_column(coluna)

    op.drop_index("ix_dissertativa_question_lesson_id", table_name="dissertativa_question")
    with op.batch_alter_table("dissertativa_question") as batch_op:
        for coluna in ("guia_gerado_em_ref", "secoes_json", "criterio_texto", "tipo", "fonte"):
            batch_op.drop_column(coluna)
