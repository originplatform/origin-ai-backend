"""LangGraph execution nodes for ORIGIN AI."""

from typing import Any, Dict, Optional
from app.approvals.service import approval_service
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.db.models.task import Task
from app.db.models.step import TaskStep
from app.db.models.agent_execution import AgentExecution
from app.db.models.tool_execution import ToolExecution
from app.graphs.state import OriginState, PlanStep
from app.tools.base import RiskLevel
from app.tools.registry import tool_registry

logger = get_logger("origin.graphs.nodes")


async def understand_and_plan_node(state: OriginState) -> OriginState:
    """Understands user command and establishes structured execution plan."""
    from app.agents.orchestrator import orchestrator_agent

    logger.info(f"Node [Plan]: Analyzing command for task '{state.task_id}'")
    updated_state = await orchestrator_agent.process(state)

    # Persist plan in DB
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == state.task_id).first()
        if task:
            task.intent = updated_state.intent
            task.execution_plan = [s.model_dump() for s in updated_state.execution_plan]
            task.selected_agents = updated_state.selected_agents
            task.selected_tools = updated_state.selected_tools
            task.status = "RUNNING"

            # Create TaskStep rows
            for s in updated_state.execution_plan:
                step_rec = TaskStep(
                    task_id=state.task_id,
                    step_number=s.step_number,
                    agent_name=s.agent_name,
                    action=s.action,
                    tool_name=s.tool_id,
                    input_data=s.input_params,
                    status="PENDING",
                )
                db.add(step_rec)
            db.commit()
    except Exception as exc:
        logger.error(f"Failed to persist task plan in database: {exc}")
    finally:
        db.close()

    updated_state.status = "EXECUTING"
    return updated_state


async def execute_step_node(state: OriginState) -> OriginState:
    """Executes the next pending step in the execution plan."""
    # Find next pending step
    next_step: Optional[PlanStep] = None
    for step in state.execution_plan:
        if step.status == "PENDING" and step.agent_name != "Verification Agent":
            next_step = step
            break

    if not next_step:
        logger.info(f"No pending agent steps remaining for task '{state.task_id}'")
        return state

    logger.info(
        f"Node [ExecuteStep]: Step {next_step.step_number} ({next_step.agent_name} -> {next_step.action})"
    )

    # 1. Dependency validation
    if next_step.dependencies:
        for dep_num in next_step.dependencies:
            dep_step = next((s for s in state.execution_plan if s.step_number == dep_num), None)
            if dep_step and dep_step.status != "COMPLETED":
                logger.warning(
                    f"Step {next_step.step_number} depends on incomplete step {dep_num} ({dep_step.status})"
                )
                next_step.status = "FAILED"
                next_step.error = f"Dependency step {dep_num} was not completed."
                state.errors.append(next_step.error)
                return state

    # 2. Risk & Approval Gate Check
    tool = tool_registry.get_tool(next_step.tool_id) if next_step.tool_id else None
    if tool and tool.risk_level == RiskLevel.REQUIRES_APPROVAL:
        if state.approval_status != "APPROVED":
            logger.info(f"Approval gate triggered for tool '{tool.tool_id}' on task '{state.task_id}'")
            db = SessionLocal()
            try:
                approval_req = approval_service.create_request(
                    db=db,
                    task_id=state.task_id,
                    tool_id=tool.tool_id,
                    proposed_action=next_step.action,
                    action_details=next_step.input_params,
                )
                state.approval_status = "PENDING"
                state.pending_approval = {
                    "approval_id": approval_req.id,
                    "tool_id": tool.tool_id,
                    "proposed_action": next_step.action,
                    "action_details": next_step.input_params,
                }
                state.status = "AWAITING_APPROVAL"
                next_step.status = "AWAITING_APPROVAL"
            finally:
                db.close()
            return state

    # 3. Step Execution
    from app.agents import get_agent

    agent = get_agent(next_step.agent_name)
    db = SessionLocal()
    context = {"db": db, "task_id": state.task_id}
    next_step.status = "RUNNING"

    try:
        step_output = {}
        if hasattr(agent, "execute_step"):
            step_output = await agent.execute_step(next_step, state, context)
        else:
            await agent.process(state, context)

        # Check for errors in output
        if isinstance(step_output, dict) and step_output.get("error"):
            err_msg = step_output["error"]
            current_retries = state.retry_counts.get(next_step.step_number, 0)
            if current_retries < settings.MAX_STEP_RETRIES:
                state.retry_counts[next_step.step_number] = current_retries + 1
                logger.warning(
                    f"Retrying step {next_step.step_number} (Attempt {current_retries + 1}/{settings.MAX_STEP_RETRIES}): {err_msg}"
                )
                next_step.status = "PENDING"
            else:
                next_step.status = "FAILED"
                next_step.error = err_msg
                state.errors.append(err_msg)
        else:
            next_step.status = "COMPLETED"
            next_step.output = step_output

            # Store in state
            agent_key = next_step.agent_name.lower().replace(" agent", "").replace(" ", "_")
            if agent_key not in state.agent_outputs:
                state.agent_outputs[agent_key] = []
            if isinstance(state.agent_outputs[agent_key], list):
                state.agent_outputs[agent_key].append(step_output)
            else:
                state.agent_outputs[agent_key] = step_output

            if next_step.tool_id:
                state.tool_execution_results[next_step.tool_id] = step_output

        # Update step record in database
        step_rec = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == state.task_id, TaskStep.step_number == next_step.step_number)
            .first()
        )
        if step_rec:
            step_rec.status = next_step.status
            step_rec.output_data = next_step.output
            step_rec.error_message = next_step.error
            db.commit()

    except Exception as exc:
        logger.error(f"Exception executing step {next_step.step_number}: {exc}")
        next_step.status = "FAILED"
        next_step.error = str(exc)
        state.errors.append(str(exc))
    finally:
        db.close()

    return state


async def verification_node(state: OriginState) -> OriginState:
    """Audits generated outputs, validates filesystem artifacts, and confirms outcomes."""
    from app.agents.verifier import verification_agent

    logger.info(f"Node [Verify]: Performing verification audit for task '{state.task_id}'")
    updated_state = await verification_agent.process(state)
    return updated_state


async def completion_report_node(state: OriginState) -> OriginState:
    """Assembles final completion report and updates persistent task status."""
    logger.info(f"Node [Complete]: Compiling completion report for task '{state.task_id}'")
    evidence = state.verification_evidence or {}
    all_success = evidence.get("all_steps_successful", True) and not state.errors

    final_status = "COMPLETED" if all_success else "FAILED"

    # Assemble downloadable files
    verified_files = evidence.get("verified_files", [])
    download_links = []
    for vf in verified_files:
        fid = vf.get("file_id")
        fname = vf.get("filename")
        download_links.append({
            "filename": fname,
            "size_bytes": vf.get("size_bytes"),
            "file_id": fid,
            "download_url": f"/api/v1/files/{fid}/download" if fid else f"/api/v1/files/raw/{fname}",
        })

    report = {
        "task_id": state.task_id,
        "user_command": state.user_command,
        "intent": state.intent,
        "objective": state.objective,
        "status": final_status,
        "total_steps": len(state.execution_plan),
        "completed_steps": evidence.get("completed_steps", 0),
        "generated_files": download_links,
        "verification_evidence": evidence,
        "agent_outputs": state.agent_outputs,
        "errors": state.errors,
    }

    state.final_result = report
    state.status = final_status

    # Persist final result in DB
    db = SessionLocal()
    try:
        from datetime import datetime, timezone

        task = db.query(Task).filter(Task.id == state.task_id).first()
        if task:
            task.status = final_status
            task.final_result = report
            task.completed_at = datetime.now(timezone.utc)
            if state.errors:
                task.error_message = "; ".join(state.errors)
            db.commit()
    except Exception as exc:
        logger.error(f"Error persisting completion report: {exc}")
    finally:
        db.close()

    return state
