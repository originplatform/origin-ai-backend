"""Centralized Tool Registry for ORIGIN AI."""

import time
from typing import Any, Dict, List, Optional
from app.core.logging import get_logger
from app.tools.base import BaseTool, RiskLevel, ToolResult

logger = get_logger("origin.tools.registry")


class ToolRegistry:
    """Universal tool registry preventing arbitrary or hallucinated tool execution."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Registers a tool in the allowlist."""
        if tool.tool_id in self._tools:
            logger.warning(f"Overwriting existing tool registration: {tool.tool_id}")
        self._tools[tool.tool_id] = tool
        logger.debug(f"Registered tool '{tool.tool_id}' ({tool.name})")

    def get_tool(self, tool_id: str) -> Optional[BaseTool]:
        """Retrieves a registered tool by its unique ID."""
        return self._tools.get(tool_id)

    def is_registered(self, tool_id: str) -> bool:
        """Checks if a tool is registered in the allowlist."""
        return tool_id in self._tools

    def list_tools(self) -> List[Dict[str, Any]]:
        """Returns catalog of all registered tools and their specifications."""
        return [
            {
                "tool_id": t.tool_id,
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level.value,
                "timeout_seconds": t.timeout_seconds,
                "required_permissions": t.required_permissions,
                "input_schema": t.input_schema.model_json_schema(),
            }
            for t in self._tools.values()
        ]

    async def execute(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """
        Executes a registered tool securely.
        Rejects unregistered tools and logs execution metrics.
        """
        tool = self.get_tool(tool_id)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Security Policy: Tool '{tool_id}' is not in the approved tool registry.",
            )

        start_time = time.time()
        logger.info(f"Executing tool '{tool_id}' with risk level '{tool.risk_level.value}'")
        try:
            result = await tool.execute(params, context)
            elapsed_ms = int((time.time() - start_time) * 1000)
            result.metadata["execution_time_ms"] = elapsed_ms
            result.metadata["tool_id"] = tool_id
            return result
        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Execution error in tool '{tool_id}': {exc}")
            return ToolResult(
                success=False,
                error=str(exc),
                metadata={"execution_time_ms": elapsed_ms, "tool_id": tool_id},
            )


tool_registry = ToolRegistry()

