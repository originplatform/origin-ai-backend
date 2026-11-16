"""User-owned contacts used by the communication agent."""

import uuid
from typing import List, Optional

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Contact(Base):
    """Owner-scoped contact details for email resolution and drafting."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("owner_id", "email_address", name="uq_contact_owner_email"),
        Index("ix_contacts_owner_name", "owner_id", "full_name"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list, nullable=True)
    organization: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), default="unverified", nullable=False, index=True
    )

    user = relationship("User", back_populates="contacts")
