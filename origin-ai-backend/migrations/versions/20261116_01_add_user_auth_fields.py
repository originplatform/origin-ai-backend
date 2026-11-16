"""Add authentication fields to the existing users table.

Revision ID: 20261116_01
Revises: 8e165bece07d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261116_01"
down_revision: Union[str, None] = "8e165bece07d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "full_name",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "users", sa.Column("hashed_password", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users", sa.Column("profile_picture", sa.String(length=2048), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.String(length=32),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))

    op.execute(
        sa.text(
            "UPDATE users "
            "SET full_name = COALESCE(NULLIF(name, ''), email) "
            "WHERE full_name IS NULL OR full_name = ''"
        )
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "profile_picture")
    op.drop_column("users", "hashed_password")
    op.drop_column("users", "full_name")
