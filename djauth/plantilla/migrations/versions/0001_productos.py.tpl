"""Tabla de productos (módulo de ejemplo).

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "productos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo", sa.String(length=40), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("precio", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modificado", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_productos_codigo", "productos", ["codigo"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_productos_codigo", table_name="productos")
    op.drop_table("productos")
