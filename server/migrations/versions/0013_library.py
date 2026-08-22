"""fase 10: biblioteca (work, work_image, work_section, material_page)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String, nullable=False, server_default="livro"),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("subtitulo", sa.String, nullable=True),
        sa.Column("autores", sa.String, nullable=True),
        sa.Column("organizadores", sa.String, nullable=True),
        sa.Column("tradutor", sa.String, nullable=True),
        sa.Column("edicao", sa.String, nullable=True),
        sa.Column("volume", sa.String, nullable=True),
        sa.Column("tomo", sa.String, nullable=True),
        sa.Column("local", sa.String, nullable=True),
        sa.Column("editora", sa.String, nullable=True),
        sa.Column("ano", sa.Integer, nullable=True),
        sa.Column("isbn", sa.String, nullable=True),
        sa.Column("doi", sa.String, nullable=True),
        sa.Column("url", sa.String, nullable=True),
        sa.Column("referencia_manual", sa.Text, nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "work_image",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("work_id", sa.Integer, sa.ForeignKey("work.id"), nullable=False),
        sa.Column("tipo", sa.String, nullable=False),
        sa.Column("path", sa.String, nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_image_work_id", "work_image", ["work_id"])

    op.create_table(
        "work_section",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("work_id", sa.Integer, sa.ForeignKey("work.id"), nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("nivel", sa.Integer, nullable=False, server_default="1"),
        sa.Column("titulo", sa.String, nullable=False),
        sa.Column("pagina_inicial", sa.Integer, nullable=False),
        sa.Column("pagina_final", sa.Integer, nullable=True),
    )
    op.create_index("ix_work_section_work_id", "work_section", ["work_id"])

    # Sem FK inline aqui de propósito: ALTER TABLE ADD COLUMN com
    # constraint de FK exige nome de constraint em modo batch no SQLite
    # (alembic recusa sem isso), e nomear uma constraint só pra essa
    # coluna não vale a complexidade -- o relacionamento do lado do
    # SQLAlchemy (models.py) funciona igual para join/query; só não há
    # enforcement de integridade referencial no schema para esta coluna.
    op.add_column("material", sa.Column("work_id", sa.Integer, nullable=True))
    op.add_column("material", sa.Column("pagina_inicial", sa.Integer, nullable=True))
    op.add_column("material", sa.Column("pagina_final", sa.Integer, nullable=True))
    op.add_column("material", sa.Column("ordem_manual", sa.Integer, nullable=True))
    op.create_index("ix_material_work_id", "material", ["work_id"])

    op.add_column("material_use", sa.Column("lido_ate", sa.Integer, nullable=True))

    op.create_table(
        "material_page",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("material_id", sa.Integer, sa.ForeignKey("material.id"), nullable=False),
        sa.Column("ordem", sa.Integer, nullable=False),
        sa.Column("pagina_obra", sa.Integer, nullable=True),
        sa.Column("image_path", sa.String, nullable=False),
        sa.Column("texto", sa.Text, nullable=True),
        sa.Column("extraido_por", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pendente"),
        sa.Column("ai_call_id", sa.Integer, sa.ForeignKey("ai_call.id"), nullable=True),
        sa.Column("erro", sa.Text, nullable=True),
        sa.Column("editado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_material_page_material_id", "material_page", ["material_id"])
    op.create_index("ix_material_page_material_ordem", "material_page", ["material_id", "ordem"], unique=True)


def downgrade() -> None:
    op.drop_table("material_page")
    op.drop_column("material_use", "lido_ate")
    op.drop_index("ix_material_work_id", table_name="material")
    op.drop_column("material", "ordem_manual")
    op.drop_column("material", "pagina_final")
    op.drop_column("material", "pagina_inicial")
    op.drop_column("material", "work_id")
    op.drop_table("work_section")
    op.drop_table("work_image")
    op.drop_table("work")
