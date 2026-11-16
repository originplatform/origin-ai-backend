"""Tasks API endpoints."""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_optional_current_user
from app.approvals.schemas import ApprovalResponse
from app.approvals.service import approval_service
from app.core.logging import get_logger
from app.core.security import SecurityError
from app.db.models import User
from app.db.models.task import Task
from app.db.session import get_db
from app.schemas.task import TaskCreateRequest, TaskResponse
from app.services.execution_service import execution_service

logger = get_logger("origin.api.tasks")
router = APIRouter()


def _require_task_access(task: Task, user: Optional[User]) -> Task:
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    if user is not None and task.user_id is not None and task.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    if user is None and task.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",
        )
    return task


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, summary="Submit Task")
async def create_task(
    payload: TaskCreateRequest,
    run_in_background: bool = Query(default=False, description="Whether to execute asynchronously in the background"),
    user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Submits a natural-language task command.
    Accepts typed or transcribed speech input.
    """
    try:
        task, initial_state = execution_service.create_and_run_task(
            db,
            payload.command,
            user_id=user.id if user is not None else None,
        )

        if run_in_background:
            asyncio.create_task(execution_service.run_task_async(initial_state))
            db.refresh(task)
            return task
        else:
            await execution_service.run_task_async(initial_state)
            db.refresh(task)
            return task
    except SecurityError as sec_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(sec_err))
    except Exception as exc:
        logger.error(f"Failed to initiate task: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task initiation error: {str(exc)}",
        )


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Get Task Status")
def get_task(
    task_id: str,
    user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves current execution status, plan, trace, and completion report."""
    task = db.query(Task).filter(Task.id == task_id).first()
    _require_task_access(task, user)
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse, summary="Cancel Task")
def cancel_task(
    task_id: str,
    user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Aborts an active or pending task execution."""
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        _require_task_access(task, user)
        task = execution_service.cancel_task(db, task_id)
        return task
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/tasks/{task_id}/approvals", response_model=List[ApprovalResponse], summary="Get Task Approvals")
def get_task_approvals(
    task_id: str,
    user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves approval requests associated with a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    _require_task_access(task, user)
    return approval_service.list_task_approvals(db, task_id)

