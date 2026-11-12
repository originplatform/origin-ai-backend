"""Task request and response schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TaskCreateRequest(BaseModel):
    """Payload for initiating a new autonomous task."""

    command: str = Field(
        ...,
        min_length=3,
        description="Natural-language task command (typed or transcribed from speech)",
        json_schema_extra={"example": "Create a professional DOCX and PDF report about autonomous AI agents and save both files in my workspace."},
    )


class TaskStepResponse(BaseModel):
    """Schema for individual step execution trace."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    step_number: int
    agent_name: str
    action: str
    tool_name: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    status: str
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskResponse(BaseModel):
    """Detailed response schema for an autonomous task."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_command: str
    intent: Optional[str] = None
    status: str
    execution_plan: Optional[List[Dict[str, Any]]] = None
    selected_agents: Optional[List[str]] = None
    selected_tools: Optional[List[str]] = None
    final_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    steps: List[TaskStepResponse] = Field(default_factory=list)
