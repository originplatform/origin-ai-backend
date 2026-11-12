"""Shopping and Booking Agent Module."""

from typing import Any, Dict, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.shopping_booking")


class ShoppingBookingAgent(BaseAgent):
    """Responsible for product discovery, comparison, and booking workflows."""

    name = "Shopping and Booking Agent"
    description = "Searches products, compares cinema showtimes, and handles booking preparation."
    system_prompt = "You are the Commerce Specialist for ORIGIN AI. Never simulate fake bookings or transactions."
    allowed_tools = ["search_products", "book_movie_tickets"]

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_id = step.tool_id or "search_products"
        params = dict(step.input_params)

        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error, "adapter_status": "unconfigured"}

        return result.data or {}

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


shopping_booking_agent = ShoppingBookingAgent()

