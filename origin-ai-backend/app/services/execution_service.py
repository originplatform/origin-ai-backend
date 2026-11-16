"""Execution Service orchestrating task lifecycle and workflow resumption."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.approvals.service import approval_service
from app.core.logging import get_logger
from app.core.security import PromptDefense, SecurityError
from app.db.models.task import Task
from app.db.models.step import TaskStep
from app.db.session import SessionLocal
from app.graphs.state import OriginState, PlanStep
from app.graphs.workflow import execute_task_lifecycle, orchestrator_graph

logger = get_logger("origin.services.execution")


class ExecutionService:
    """Coordinates lifecycle of user tasks from prompt to completion."""

    @staticmethod
    def create_and_run_task(
        db: Session,
        user_command: str,
        *,
        user_id: Optional[str] = None,
        background_task: bool = False,
    ) -> Task:
        """
        Creates a new task, validates security policies, and initiates execution.
        """
        # 1. Security inspection
        is_safe, reason = PromptDefense.inspect_prompt(user_command)
        if not is_safe:
            raise SecurityError(f"Command blocked by security policy: {reason}")

        # 2. Persist initial task record and pin the authenticated owner.
        task = Task(
            user_id=user_id,
            user_command=user_command,
            status="PENDING",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # 3. Initialize typed LangGraph state with the authenticated owner context.
        initial_state = OriginState(
            task_id=task.id,
            user_id=user_id,
            user_command=user_command,
        )

        return task, initial_state

    @staticmethod
    async def run_task_async(initial_state: OriginState) -> OriginState:
        """Executes task through LangGraph workflow."""
        return await execute_task_lifecycle(initial_state)

    @staticmethod
    def cancel_task(db: Session, task_id: str) -> Task:
        """Cancels an active or pending task."""
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        if task.status in ("COMPLETED", "FAILED", "CANCELLED"):
            return task

        task.status = "CANCELLED"
        task.error_message = "Task cancelled by user request."
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(task)
        logger.info(f"Task '{task_id}' marked as CANCELLED")
        return task

    @staticmethod
    async def resume_task_after_approval(
        db: Session,
        approval_id: str,
        decision: str,
        user_notes: Optional[str] = None,
    ) -> Task:
        """
        Processes human approval decision and resumes the LangGraph workflow if approved.
        """
        approval = approval_service.record_decision(db, approval_id, decision, user_notes)
        task = db.query(Task).filter(Task.id == approval.task_id).first()

        if decision == "REJECTED":
            return task

        # Reconstruct state from DB to resume
        steps = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task.id)
            .order_by(TaskStep.step_number)
            .all()
        )

        plan_steps = [
            PlanStep(
                step_number=s.step_number,
                agent_name=s.agent_name,
                action=s.action,
                tool_id=s.tool_name,
                input_params=s.input_data or {},
                status="PENDING" if s.status == "AWAITING_APPROVAL" else s.status,
                output=s.output_data,
                error=s.error_message,
            )
            for s in steps
        ]

        resumed_state = OriginState(
            task_id=task.id,
            user_command=task.user_command,
            intent=task.intent,
            execution_plan=plan_steps,
            selected_agents=task.selected_agents or [],
            selected_tools=task.selected_tools or [],
            approval_status="APPROVED",
            status="EXECUTING",
        )

        # Resume LangGraph execution
        logger.info(f"Resuming LangGraph workflow for approved task '{task.id}'")
        final_state = await orchestrator_graph.ainvoke(resumed_state)
        db.refresh(task)
        return task


execution_service = ExecutionService()

