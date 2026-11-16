"""Create persistent refresh-token sessions.

Revision ID: 20261116_02
Revises: 20261116_01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261116_02"
down_revision: Union[str, None] = "20261116_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_NAME = "refresh_tokens"
_EXPECTED_COLUMNS = {
    "id": (36, False),
    "user_id": (36, False),
    "token_hash": (64, False),
    "family_id": (36, False),
    "expires_at": (None, False),
    "revoked_at": (None, True),
    "replaced_by_token_id": (36, True),
    "device_name": (255, True),
    "user_agent": (512, True),
    "created_at": (None, False),
    "updated_at": (None, False),
}
_EXPECTED_INDEXES = (
    ("ix_refresh_tokens_user_id", ["user_id"], False),
    ("ix_refresh_tokens_token_hash", ["token_hash"], True),
    ("ix_refresh_tokens_family_id", ["family_id"], False),
    ("ix_refresh_tokens_expires_at", ["expires_at"], False),
    ("ix_refresh_tokens_replaced_by_token_id", ["replaced_by_token_id"], False),
)
_EXPECTED_FOREIGN_KEYS = {
    (("user_id",), "users", ("id",), "CASCADE"),
    (
        ("replaced_by_token_id",),
        "refresh_tokens",
        ("id",),
        "SET NULL",
    ),
}


def _validate_existing_table(inspector) -> None:
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE_NAME)}
    for name, (length, nullable) in _EXPECTED_COLUMNS.items():
        column = columns.get(name)
        if column is None or column["nullable"] != nullable:
            raise RuntimeError(
                f"Existing {_TABLE_NAME} table is missing or has incompatible column {name}."
            )
        if length is not None and (
            not isinstance(column["type"], sa.String)
            or column["type"].length != length
        ):
            raise RuntimeError(
                f"Existing {_TABLE_NAME}.{name} has an incompatible type."
            )
        if length is None and not isinstance(column["type"], sa.DateTime):
            raise RuntimeError(
                f"Existing {_TABLE_NAME}.{name} has an incompatible type."
            )

    if inspector.get_pk_constraint(_TABLE_NAME).get("constrained_columns") != ["id"]:
        raise RuntimeError(f"Existing {_TABLE_NAME} table has an incompatible primary key.")

    foreign_keys = {
        (
            tuple(foreign_key.get("constrained_columns") or ()),
            foreign_key["referred_table"],
            tuple(foreign_key.get("referred_columns") or ()),
            (foreign_key.get("options") or {}).get("ondelete", "").upper(),
        )
        for foreign_key in inspector.get_foreign_keys(_TABLE_NAME)
    }
    if not _EXPECTED_FOREIGN_KEYS.issubset(foreign_keys):
        raise RuntimeError(f"Existing {_TABLE_NAME} table has incompatible foreign keys.")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE_NAME):
        _validate_existing_table(inspector)
    else:
        op.create_table(
            _TABLE_NAME,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("family_id", sa.String(length=36), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by_token_id", sa.String(length=36), nullable=True),
            sa.Column("device_name", sa.String(length=255), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["replaced_by_token_id"],
                ["refresh_tokens.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"]: index for index in inspector.get_indexes(_TABLE_NAME)}
    for name, columns, unique in _EXPECTED_INDEXES:
        existing_index = indexes.get(name)
        if existing_index is not None:
            if (
                existing_index["column_names"] != columns
                or existing_index["unique"] != unique
            ):
                raise RuntimeError(
                    f"Existing index {name} on {_TABLE_NAME} is incompatible."
                )
            continue
        op.create_index(name, _TABLE_NAME, columns, unique=unique)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_replaced_by_token_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
