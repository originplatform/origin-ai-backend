"""Approval request database model."""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class ApprovalRequest(Base):
    """Persistent gate for high-risk actions requiring explicit human authorization."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False, index=True
    )
    step_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(255), nullable=False)
    action_details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(32), default="REQUIRES_APPROVAL", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, APPROVED, REJECTED
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task = relationship("Task", back_populates="approvals")

