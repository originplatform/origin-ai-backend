"""User database model."""

import uuid
from typing import Optional
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym
from app.db.base import Base


class User(Base):
    """User identity and authentication-provider data."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legacy_name: Mapped[Optional[str]] = mapped_column(
        "name", String(255), nullable=True
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile_picture: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_provider: Mapped[str] = mapped_column(
        String(32), default="local", nullable=False
    )
    google_sub: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )

    name = synonym("full_name")
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

