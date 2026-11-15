"""Canonical identifiers and deterministic aliases for executable agents."""

import re
from typing import Dict

from app.agents.base import BaseAgent
from app.agents.browser import browser_agent
from app.agents.communication import communication_agent
from app.agents.document import document_agent
from app.agents.file_manager import file_manager_agent
from app.agents.research import research_agent
from app.agents.shopping_booking import shopping_booking_agent
from app.agents.verifier import verification_agent

AGENT_REGISTRY: Dict[str, BaseAgent] = {
    "research": research_agent,
    "document": document_agent,
    "file_manager": file_manager_agent,
    "communication": communication_agent,
    "browser": browser_agent,
    "shopping_booking": shopping_booking_agent,
    "verification": verification_agent,
}

_AGENT_ALIASES = {
    "research": "research",
    "researchagent": "research",
    "research agent": "research",
    "document": "document",
    "documentagent": "document",
    "document agent": "document",
    "file_manager": "file_manager",
    "filemanager": "file_manager",
    "filemanageragent": "file_manager",
    "file manager agent": "file_manager",
    "file management agent": "file_manager",
    "communication": "communication",
    "communicationagent": "communication",
    "communication agent": "communication",
    "browser": "browser",
    "browseragent": "browser",
    "browser agent": "browser",
    "browser automation agent": "browser",
    "shopping_booking": "shopping_booking",
    "shoppingbooking": "shopping_booking",
    "shoppingbookingagent": "shopping_booking",
    "shopping booking agent": "shopping_booking",
    "shopping and booking agent": "shopping_booking",
    "verification": "verification",
    "verificationagent": "verification",
    "verification agent": "verification",
}


def normalize_agent_id(agent_name: str) -> str:
    """Resolve a known display name, class name, or canonical ID without guessing."""
    normalized = re.sub(r"\s+", " ", agent_name.strip()).casefold()
    compact = re.sub(r"[\s_-]+", "", normalized)
    agent_id = _AGENT_ALIASES.get(normalized) or _AGENT_ALIASES.get(compact)
    if agent_id is None or agent_id not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent identifier '{agent_name}'.")
    return agent_id


def get_agent(agent_name: str) -> BaseAgent:
    """Resolve a canonical ID or supported legacy alias to its implementation."""
    return AGENT_REGISTRY[normalize_agent_id(agent_name)]


__all__ = ["AGENT_REGISTRY", "get_agent", "normalize_agent_id"]
