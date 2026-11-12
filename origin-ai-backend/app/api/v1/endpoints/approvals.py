"""Approvals API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.approvals.schemas import ApprovalDecisionRequest, ApprovalResponse
from app.approvals.service import approval_service
from app.core.logging import get_logger
from app.db.session import get_db
from app.services.execution_service import execution_service

logger = get_logger("origin.api.approvals")
router = APIRouter()


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalResponse,
    summary="Submit Human Approval Decision",
)
async def submit_approval_decision(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
):
    """
    Submits explicit human decision (APPROVED or REJECTED) for a high-risk operation.
    If approved, automatically resumes the paused LangGraph workflow.
    """
    try:
        updated_approval = approval_service.get_by_id(db, approval_id)
        if not updated_approval:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request '{approval_id}' not found.",
            )

        if updated_approval.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Approval request '{approval_id}' has already been processed.",
            )

        await execution_service.resume_task_after_approval(
            db=db,
            approval_id=approval_id,
            decision=payload.decision,
            user_notes=payload.user_notes,
        )

        db.refresh(updated_approval)
        return updated_approval
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        logger.error(f"Error processing approval decision: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Decision processing failed: {str(exc)}",
        )

