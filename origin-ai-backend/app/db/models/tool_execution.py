"""Tool execution trace database model."""

import uuid
from typing import Optional, Dict, Any
from sqlalchemy import String, Integer, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class ToolExecution(Base):
    """Audit and telemetry record for universal tool executions."""

    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False, index=True
    )
    step_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_params: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS", nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    task = relationship("Task", back_populates="tool_executions")

