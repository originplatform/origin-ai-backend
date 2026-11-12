"""Graphs package."""

from app.graphs.state import OriginState, PlanStep


def get_orchestrator_graph():
    """Lazily returns compiled workflow graph."""
    from app.graphs.workflow import orchestrator_graph
    return orchestrator_graph


async def execute_task_lifecycle(initial_state: OriginState) -> OriginState:
    """Lazily executes task workflow."""
    from app.graphs.workflow import execute_task_lifecycle as _exec
    return await _exec(initial_state)


__all__ = [
    "OriginState",
    "PlanStep",
    "get_orchestrator_graph",
    "execute_task_lifecycle",
]
