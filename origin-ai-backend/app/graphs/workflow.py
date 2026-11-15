"""LangGraph Workflow definition and execution orchestration."""

from langgraph.graph import StateGraph, START, END
from app.core.logging import get_logger
from app.graphs.nodes import (
    understand_and_plan_node,
    execute_step_node,
    verification_node,
    completion_report_node,
)
from app.graphs.routing import should_continue
from app.graphs.state import OriginState

logger = get_logger("origin.graphs.workflow")


def build_orchestrator_graph():
    """Builds and compiles the cyclic LangGraph autonomous workflow."""
    workflow = StateGraph(OriginState)

    # 1. Register nodes
    workflow.add_node("plan", understand_and_plan_node)
    workflow.add_node("execute_step", execute_step_node)
    workflow.add_node("verify", verification_node)
    workflow.add_node("complete", completion_report_node)

    # 2. Define transitions
    workflow.add_edge(START, "plan")
    workflow.add_edge("plan", "execute_step")

    workflow.add_conditional_edges(
        "execute_step",
        should_continue,
        {
            "execute_step": "execute_step",
            "verify": "verify",
            "end": END,
        },
    )

    workflow.add_edge("verify", "complete")
    workflow.add_edge("complete", END)

    return workflow.compile()


# Global compiled execution graph
orchestrator_graph = build_orchestrator_graph()


async def execute_task_lifecycle(initial_state: OriginState) -> OriginState:
    """Executes the autonomous agent graph for a task."""
    logger.info(f"Initiating LangGraph execution for task '{initial_state.task_id}'")
    try:
        final_output = await orchestrator_graph.ainvoke(initial_state)
    except Exception as exc:
        logger.exception("Workflow failed for task '%s'", initial_state.task_id)
        initial_state.errors.append(f"Workflow execution failed: {exc}")
        initial_state.status = "FAILED"
        initial_state.verification_evidence = {
            "all_steps_successful": False,
            "discrepancies": [str(exc)],
        }
        return await completion_report_node(initial_state)

    if isinstance(final_output, dict):
        return OriginState.model_validate(final_output)
    return final_output
