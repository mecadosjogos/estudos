"""fase 4: fila de transcrição, transcript e segmentos

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcription_job",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False),
        sa.Column("target", sa.String, nullable=False, server_default="gpu_worker"),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("claim_token", sa.String, nullable=True),
        sa.Column("claimed_by", sa.String, nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_transcription_job_target_status",
        "transcription_job",
        ["target", "status"],
    )

    op.create_table(
        "transcript",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=False, unique=True),
        sa.Column("engine", sa.String, nullable=False),
        sa.Column("worker_name", sa.String, nullable=False),
        sa.Column("full_text", sa.Text, nullable=False),
        sa.Column("duration_s", sa.Float, nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "transcript_segment",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("transcript_id", sa.Integer, sa.ForeignKey("transcript.id"), nullable=False),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("end_s", sa.Float, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("words_json", sa.Text, nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_transcript_segment_transcript_id", "transcript_segment", ["transcript_id"]
    )


def downgrade() -> None:
    op.drop_table("transcript_segment")
    op.drop_table("transcript")
    op.drop_index("ix_transcription_job_target_status", table_name="transcription_job")
    op.drop_table("transcription_job")
