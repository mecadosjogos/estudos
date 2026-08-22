"""fase 9: materiais e Google Docs (tabela material, material_use, tags, sync)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subject", sa.Column("drive_folder_id", sa.String, nullable=True))
    op.add_column("subject", sa.Column("doc_modelo_id", sa.String, nullable=True))

    op.create_table(
        "material_tipo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String, nullable=False),
        sa.Column("rotulo", sa.String, nullable=False),
        sa.Column("icone", sa.String, nullable=True),
        sa.Column("cor", sa.String, nullable=True),
    )
    op.create_index("ix_material_tipo_slug", "material_tipo", ["slug"], unique=True)

    from app.seed_data import MATERIAL_TIPOS

    tipo_table = sa.table(
        "material_tipo",
        sa.column("slug", sa.String),
        sa.column("rotulo", sa.String),
    )
    op.bulk_insert(tipo_table, MATERIAL_TIPOS)

    op.create_table(
        "material",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo_id", sa.Integer, sa.ForeignKey("material_tipo.id"), nullable=True),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("origem", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("path", sa.String, nullable=True),
        sa.Column("url", sa.String, nullable=True),
        sa.Column("mime", sa.String, nullable=True),
        sa.Column("conteudo_md", sa.Text, nullable=True),
        sa.Column("indexado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gdoc_id", sa.String, nullable=True),
        sa.Column("gdoc_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_material_gdoc_id", "material", ["gdoc_id"], unique=True, sqlite_where=sa.text("gdoc_id IS NOT NULL"))

    op.create_table(
        "material_use",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("material_id", sa.Integer, sa.ForeignKey("material.id"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subject.id"), nullable=False),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lesson.id"), nullable=True),
        sa.Column("pagina_inicial", sa.Integer, nullable=True),
        sa.Column("pagina_final", sa.Integer, nullable=True),
        sa.Column("rotulo", sa.String, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_material_use_material_id", "material_use", ["material_id"])
    op.create_index("ix_material_use_subject_id", "material_use", ["subject_id"])
    op.create_index("ix_material_use_lesson_id", "material_use", ["lesson_id"])

    op.create_table(
        "material_tag",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("material_id", sa.Integer, sa.ForeignKey("material.id"), nullable=False),
        sa.Column("tag", sa.String, nullable=False),
    )
    op.create_index("ix_material_tag_material_tag", "material_tag", ["material_id", "tag"], unique=True)


def downgrade() -> None:
    op.drop_table("material_tag")
    op.drop_table("material_use")
    op.drop_index("ix_material_gdoc_id", table_name="material")
    op.drop_table("material")
    op.drop_table("material_tipo")
    op.drop_column("subject", "doc_modelo_id")
    op.drop_column("subject", "drive_folder_id")
