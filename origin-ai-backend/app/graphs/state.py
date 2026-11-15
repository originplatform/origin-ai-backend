"""Typed Shared State for LangGraph Autonomous Execution Engine."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """Specification of a planned execution step."""

    step_number: int
    agent_name: str
    action: str
    tool_id: Optional[str] = None
    input_params: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[int] = Field(default_factory=list)
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, AWAITING_APPROVAL, SKIPPED
    error: Optional[str] = None
    output: Optional[Dict[str, Any]] = None


class OriginState(BaseModel):
    """
    Central typed execution state passed through LangGraph nodes.
    Supports complex multi-step orchestration, branching, and verification.
    """

    task_id: str
    user_command: str
    intent: Optional[str] = None
    objective: Optional[str] = None
    execution_plan: List[PlanStep] = Field(default_factory=list)
    planning_warnings: List[str] = Field(default_factory=list)
    selected_agents: List[str] = Field(default_factory=list)
    selected_tools: List[str] = Field(default_factory=list)
    current_step_index: int = 0
    step_dependencies: Dict[int, List[int]] = Field(default_factory=dict)
    agent_outputs: Dict[str, Any] = Field(default_factory=dict)
    tool_execution_results: Dict[str, Any] = Field(default_factory=dict)
    research_queries: List[str] = Field(default_factory=list)
    research_sources: List[Dict[str, Any]] = Field(default_factory=list)
    research_findings: List[str] = Field(default_factory=list)
    research_summary: str = ""
    report_sections: List[Dict[str, str]] = Field(default_factory=list)
    document_title: str = ""
    document_conversion: bool = False
    source_document_content: str = ""
    document_outputs: List[Dict[str, Any]] = Field(default_factory=list)
    generated_files: List[Dict[str, Any]] = Field(default_factory=list)
    verification_results: Dict[str, Any] = Field(default_factory=dict)
    approval_status: str = "NOT_REQUIRED"  # NOT_REQUIRED, PENDING, APPROVED, REJECTED
    pending_approval: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)
    retry_counts: Dict[int, int] = Field(default_factory=dict)
    verification_evidence: Dict[str, Any] = Field(default_factory=dict)
    final_result: Optional[Dict[str, Any]] = None
    status: str = "PENDING"  # PENDING, PLANNING, EXECUTING, AWAITING_APPROVAL, VERIFYING, COMPLETED, FAILED, CANCELLED
