"""Encrypted Gmail account connections for an authenticated owner."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GmailConnection(Base):
    """Persists the owner-scoped Gmail access state and secure tokens."""

    __tablename__ = "gmail_connections"
    __table_args__ = (UniqueConstraint("owner_id", name="uq_gmail_connection_owner"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    google_sub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(32), default="Bearer", nullable=False)
    scopes: Mapped[Optional[dict]] = mapped_column(JSON, default=dict, nullable=True)
    connection_status: Mapped[str] = mapped_column(
        String(32), default="disconnected", nullable=False, index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=True
    )

    user = relationship("User", back_populates="gmail_connections")
