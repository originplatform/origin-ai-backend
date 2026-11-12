"""Agent execution trace database model."""

import uuid
from typing import Optional, Dict, Any
from sqlalchemy import String, Integer, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class AgentExecution(Base):
    """Execution trace and diagnostic state per agent invocation."""

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False)
    input_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    task = relationship("Task", back_populates="agent_executions")

