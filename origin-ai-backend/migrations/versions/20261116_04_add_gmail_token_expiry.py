"""Track Gmail access-token expiry for safe token refresh.

Revision ID: 20261116_04
Revises: 20261116_03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261116_04"
down_revision: Union[str, None] = "20261116_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("gmail_connections"):
        columns = {column["name"] for column in inspector.get_columns("gmail_connections")}
        if "expires_at" not in columns:
            with op.batch_alter_table("gmail_connections") as batch_op:
                batch_op.add_column(
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
                )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("gmail_connections"):
        columns = {column["name"] for column in inspector.get_columns("gmail_connections")}
        if "expires_at" in columns:
            with op.batch_alter_table("gmail_connections") as batch_op:
                batch_op.drop_column("expires_at")
