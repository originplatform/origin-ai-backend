"""Add owner-scoped contacts and Gmail connection tables.

Revision ID: 20261116_03
Revises: 20261116_02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261116_03"
down_revision: Union[str, None] = "20261116_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("contacts"):
        op.create_table(
            "contacts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=False),
            sa.Column("email_address", sa.String(length=255), nullable=False),
            sa.Column("aliases", sa.JSON(), nullable=True),
            sa.Column("organization", sa.String(length=255), nullable=True),
            sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="unverified"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "email_address",
                name="uq_contact_owner_email",
            ),
        )
        op.create_index("ix_contacts_owner_id", "contacts", ["owner_id"], unique=False)
        op.create_index("ix_contacts_verification_status", "contacts", ["verification_status"], unique=False)
        op.create_index("ix_contacts_owner_name", "contacts", ["owner_id", "full_name"], unique=False)

    if not inspector.has_table("gmail_connections"):
        op.create_table(
            "gmail_connections",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("email_address", sa.String(length=255), nullable=False),
            sa.Column("google_sub", sa.String(length=255), nullable=True),
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
            sa.Column("token_type", sa.String(length=32), nullable=False, server_default="Bearer"),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("connection_status", sa.String(length=32), nullable=False, server_default="disconnected"),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("owner_id", name="uq_gmail_connection_owner"),
        )
        op.create_index("ix_gmail_connections_owner_id", "gmail_connections", ["owner_id"], unique=True)
        op.create_index("ix_gmail_connections_connection_status", "gmail_connections", ["connection_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_gmail_connections_connection_status", table_name="gmail_connections")
    op.drop_index("ix_gmail_connections_owner_id", table_name="gmail_connections")
    op.drop_table("gmail_connections")

    op.drop_index("ix_contacts_owner_name", table_name="contacts")
    op.drop_index("ix_contacts_verification_status", table_name="contacts")
    op.drop_index("ix_contacts_owner_id", table_name="contacts")
    op.drop_table("contacts")
