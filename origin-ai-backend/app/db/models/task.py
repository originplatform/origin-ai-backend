"""Task database model."""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Task(Base):
    """Core autonomous task lifecycle model."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    user_command: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )
    execution_plan: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    selected_agents: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    selected_tools: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    final_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", back_populates="tasks")
    steps = relationship(
        "TaskStep", back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.step_number"
    )
    agent_executions = relationship(
        "AgentExecution", back_populates="task", cascade="all, delete-orphan"
    )
    tool_executions = relationship(
        "ToolExecution", back_populates="task", cascade="all, delete-orphan"
    )
    approvals = relationship(
        "ApprovalRequest", back_populates="task", cascade="all, delete-orphan"
    )
    files = relationship(
        "GeneratedFile", back_populates="task", cascade="all, delete-orphan"
    )

