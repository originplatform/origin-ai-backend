"""Base Tool Abstraction for Universal Tool Execution System."""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW_RISK = "LOW_RISK"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class ToolResult(BaseModel):
    """Normalized result returned by every tool execution."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base class for all registered ORIGIN AI tools."""

    tool_id: str
    name: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel] = ToolResult
    risk_level: RiskLevel = RiskLevel.LOW_RISK
    timeout_seconds: int = 30
    required_permissions: List[str] = []

    def validate_input(self, raw_params: Dict[str, Any]) -> BaseModel:
        """Validates input payload against tool schema."""
        return self.input_schema.model_validate(raw_params)

    @abstractmethod
    async def run(self, input_params: BaseModel, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        """Executes the specific tool operation."""
        pass

    async def execute(self, raw_params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        """Validates input, enforces execution timeout, and handles uncaught exceptions."""
        try:
            validated_input = self.validate_input(raw_params)
            return await asyncio.wait_for(
                self.run(validated_input, context),
                timeout=float(self.timeout_seconds),
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Execution of tool '{self.tool_id}' timed out after {self.timeout_seconds} seconds.",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Error executing tool '{self.tool_id}': {str(exc)}",
            )

