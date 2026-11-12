"""Communication Agent Module."""

from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.communication")


class CommunicationAgent(BaseAgent):
    """Responsible for preparing and drafting email and message communications."""

    name = "Communication Agent"
    description = "Drafts emails, attaches authorized workspace files, and handles communication workflows."
    system_prompt = "You are the Communication Specialist for ORIGIN AI. Formulate professional correspondence."
    allowed_tools = ["draft_email", "send_email"]

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_id = step.tool_id or "draft_email"
        params = dict(step.input_params)

        # Check if attachments should be picked up from preceding file discovery
        if not params.get("attachments"):
            file_mgr_data = state.agent_outputs.get("file_manager", {})
            found_files = file_mgr_data.get("files", [])
            if found_files:
                params["attachments"] = [found_files[0]["filename"]]

        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error}

        draft_data = result.data or {}
        return draft_data

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


communication_agent = CommunicationAgent()

