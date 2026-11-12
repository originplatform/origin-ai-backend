"""File metadata schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class FileMetadataResponse(BaseModel):
    """Catalog item for workspace files."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    task_id: Optional[str] = None
    filename: str
    file_path: str
    file_type: str
    file_size_bytes: int
    mime_type: str
    file_hash: Optional[str] = None
    download_url: str
    created_at: Optional[datetime] = None
