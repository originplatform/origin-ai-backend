"""Tests for human approval workflow and execution pausing/resumption."""

import pytest
from app.db.session import SessionLocal
from app.db.models.task import Task
from app.approvals.service import approval_service
from app.services.execution_service import execution_service


def test_approval_creation_and_rejection():
    db = SessionLocal()
    try:
        # Create a test task
        task = Task(user_command="Send email to partner", status="RUNNING")
        db.add(task)
        db.commit()
        db.refresh(task)

        # Trigger approval
        req = approval_service.create_request(
            db=db,
            task_id=task.id,
            tool_id="send_email",
            proposed_action="Send email to partner",
            action_details={"to_email": "partner@example.com", "subject": "Hello"},
        )
        assert req.status == "PENDING"
        db.refresh(task)
        assert task.status == "AWAITING_APPROVAL"

        # Reject approval
        updated = approval_service.record_decision(
            db=db,
            approval_id=req.id,
            decision="REJECTED",
            user_notes="Not authorized at this time",
        )
        assert updated.status == "REJECTED"
        db.refresh(task)
        assert task.status == "CANCELLED"
    finally:
        db.close()


def test_approval_approval_decision():
    db = SessionLocal()
    try:
        task = Task(user_command="Deploy update", status="RUNNING")
        db.add(task)
        db.commit()
        db.refresh(task)

        req = approval_service.create_request(
            db=db,
            task_id=task.id,
            tool_id="send_email",
            proposed_action="Send status update",
            action_details={"to_email": "team@example.com"},
        )

        updated = approval_service.record_decision(
            db=db,
            approval_id=req.id,
            decision="APPROVED",
            user_notes="Looks good, proceed.",
        )
        assert updated.status == "APPROVED"
        db.refresh(task)
        assert task.status == "RUNNING"
    finally:
        db.close()

