"""init tables

Revision ID: 0001
Revises:
Create Date: 2026-11-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "posted_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link", sa.String(1024), nullable=False),
        sa.Column(
            "posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_posted_items_link", "posted_items", ["link"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_posted_items_link", table_name="posted_items")
    op.drop_table("posted_items")
    op.drop_table("items")
