"""File Management Agent Module."""

from typing import Any, Dict, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.file_manager")


class FileManagerAgent(BaseAgent):
    """Responsible for safe local workspace file operations and organization."""

    name = "File Management Agent"
    description = "Searches, reads, organizes, and prepares downloads strictly within the authorized workspace."
    system_prompt = "You are the File Management Specialist for ORIGIN AI. Ensure safe, sandboxed file operations."
    allowed_tools = [
        "search_workspace_files",
        "read_document",
        "copy_move_file",
        "prepare_download",
    ]

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_id = step.tool_id or "search_workspace_files"
        params = dict(step.input_params)

        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error}

        return result.data or {}

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


file_manager_agent = FileManagerAgent()

