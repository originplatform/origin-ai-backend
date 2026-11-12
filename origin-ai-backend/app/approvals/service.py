"""Approval Service managing persistent approval requests and decisions."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from app.core.logging import get_logger
from app.db.models.approval import ApprovalRequest
from app.db.models.task import Task

logger = get_logger("origin.approvals.service")


class ApprovalService:
    """Manages creation, tracking, and decisions for high-risk operations."""

    @staticmethod
    def create_request(
        db: Session,
        task_id: str,
        tool_id: str,
        proposed_action: str,
        action_details: Dict[str, Any],
        step_id: Optional[str] = None,
    ) -> ApprovalRequest:
        """Persists a new approval request and transitions task to AWAITING_APPROVAL."""
        req = ApprovalRequest(
            task_id=task_id,
            step_id=step_id,
            tool_id=tool_id,
            proposed_action=proposed_action,
            action_details=action_details,
            risk_level="REQUIRES_APPROVAL",
            status="PENDING",
        )
        db.add(req)

        # Update task status to AWAITING_APPROVAL
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "AWAITING_APPROVAL"

        db.commit()
        db.refresh(req)
        logger.info(f"Created ApprovalRequest '{req.id}' for task '{task_id}' (Tool: {tool_id})")
        return req

    @staticmethod
    def get_by_id(db: Session, approval_id: str) -> Optional[ApprovalRequest]:
        """Retrieves an approval request by its ID."""
        return db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()

    @staticmethod
    def get_pending_by_task(db: Session, task_id: str) -> List[ApprovalRequest]:
        """Returns all pending approval requests for a task."""
        return (
            db.query(ApprovalRequest)
            .filter(ApprovalRequest.task_id == task_id, ApprovalRequest.status == "PENDING")
            .all()
        )

    @staticmethod
    def list_task_approvals(db: Session, task_id: str) -> List[ApprovalRequest]:
        """Returns all approvals for a task."""
        return (
            db.query(ApprovalRequest)
            .filter(ApprovalRequest.task_id == task_id)
            .order_by(ApprovalRequest.created_at.desc())
            .all()
        )

    @staticmethod
    def record_decision(
        db: Session,
        approval_id: str,
        decision: str,
        user_notes: Optional[str] = None,
    ) -> ApprovalRequest:
        """Records user decision on an approval request."""
        req = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
        if not req:
            raise ValueError(f"Approval request '{approval_id}' not found.")

        if req.status != "PENDING":
            raise ValueError(f"Approval request '{approval_id}' has already been decided ({req.status}).")

        norm_decision = decision.strip().upper()
        if norm_decision not in ("APPROVED", "REJECTED"):
            raise ValueError("Decision must be either 'APPROVED' or 'REJECTED'.")

        req.status = norm_decision
        req.decision = norm_decision
        req.decided_at = datetime.now(timezone.utc)
        req.user_notes = user_notes

        task = db.query(Task).filter(Task.id == req.task_id).first()
        if task:
            if norm_decision == "REJECTED":
                task.status = "CANCELLED"
                task.error_message = f"Operation rejected by user: {user_notes or 'No reason provided.'}"
            else:
                task.status = "RUNNING"

        db.commit()
        db.refresh(req)
        logger.info(f"ApprovalRequest '{approval_id}' recorded decision: {norm_decision}")
        return req


approval_service = ApprovalService()

