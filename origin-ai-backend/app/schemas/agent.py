"""Agent metadata schemas."""

from typing import List
from pydantic import BaseModel


class AgentInfoResponse(BaseModel):
    """Public specification of an available specialized agent."""

    name: str
    description: str
    system_prompt_excerpt: str
    allowed_tools: List[str]

