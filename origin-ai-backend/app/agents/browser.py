"""Browser Automation Agent Module."""

from typing import Any, Dict, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.browser")


class BrowserAutomationAgent(BaseAgent):
    """Responsible for controlled browser interaction and web automation."""

    name = "Browser Automation Agent"
    description = "Navigates websites, fills forms, and extracts information using Playwright adapter."
    system_prompt = "You are the Browser Automation Specialist for ORIGIN AI. Operate web interfaces safely."
    allowed_tools = ["browser_navigate", "browser_submit_form"]

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_id = step.tool_id or "browser_navigate"
        params = dict(step.input_params)

        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error, "adapter_status": "unconfigured"}

        return result.data or {}

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


browser_agent = BrowserAutomationAgent()

