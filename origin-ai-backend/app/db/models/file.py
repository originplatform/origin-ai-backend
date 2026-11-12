"""Generated file metadata model."""

import uuid
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class GeneratedFile(Base):
    """Catalog of files created by ORIGIN AI in authorized workspaces."""

    __tablename__ = "generated_files"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    task = relationship("Task", back_populates="files")

