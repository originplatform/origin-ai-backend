"""Base Agent abstraction."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.core.logging import get_logger
from app.graphs.state import OriginState

logger = get_logger("origin.agents.base")


class BaseAgent(ABC):
    """Abstract base class for all specialized ORIGIN AI agents."""

    name: str
    description: str
    system_prompt: str
    allowed_tools: List[str] = []

    @abstractmethod
    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        """Processes current state and returns updated state."""
        pass

