"""Conditional routing logic for the LangGraph orchestrator."""

from app.graphs.state import OriginState


def should_continue(state: OriginState) -> str:
    """
    Decides next node transition:
    - 'end': if execution is paused for approval, cancelled, or failed.
    - 'execute_step': if there are more pending task steps.
    - 'verify': when all execution steps have finished and ready for verification.
    """
    from app.agents.registry import normalize_agent_id

    if state.status == "AWAITING_APPROVAL":
        return "end"

    if state.status == "FAILED" and not any(s.status == "PENDING" for s in state.execution_plan):
        return "end"

    # Are there any pending steps (excluding verification agent)?
    has_pending = any(
        s.status == "PENDING" and normalize_agent_id(s.agent_name) != "verification"
        for s in state.execution_plan
    )

    if has_pending:
        return "execute_step"

    return "verify"
