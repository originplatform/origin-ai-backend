"""Specialized Agents endpoint."""

from typing import List
from fastapi import APIRouter
from app.agents import AGENT_REGISTRY
from app.schemas.agent import AgentInfoResponse

router = APIRouter()


@router.get("/agents", response_model=List[AgentInfoResponse], summary="List Specialized Agents")
def list_agents():
    """Returns directory of all available specialized agents, their roles, and permitted tools."""
    return [
        AgentInfoResponse(
            name=agent.name,
            description=agent.description,
            system_prompt_excerpt=agent.system_prompt[:120] + "...",
            allowed_tools=agent.allowed_tools,
        )
        for agent in AGENT_REGISTRY.values()
    ]

