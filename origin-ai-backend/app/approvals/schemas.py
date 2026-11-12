"""Approval Request and Decision Schemas."""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecisionRequest(BaseModel):
    """Payload for submitting human approval decision."""

    decision: str = Field(description="'APPROVED' or 'REJECTED'")
    user_notes: Optional[str] = Field(default=None, description="Optional reasoning or constraints")


class ApprovalResponse(BaseModel):
    """Public representation of an approval request."""

    id: str
    task_id: str
    step_id: Optional[str] = None
    tool_id: str
    proposed_action: str
    action_details: Dict[str, Any]
    risk_level: str
    status: str
    decision: Optional[str] = None
    decided_at: Optional[datetime] = None
    user_notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
