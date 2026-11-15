"""Agents package and unified lookup directory."""

from typing import Dict
from app.agents.base import BaseAgent
from app.agents.communication import CommunicationAgent, communication_agent
from app.agents.document import DocumentAgent, document_agent
from app.agents.file_manager import FileManagerAgent, file_manager_agent
from app.agents.research import ResearchAgent, research_agent
from app.agents.browser import BrowserAutomationAgent, browser_agent
from app.agents.shopping_booking import ShoppingBookingAgent, shopping_booking_agent
from app.agents.verifier import VerificationAgent, verification_agent
from app.agents.registry import AGENT_REGISTRY as EXECUTION_AGENT_REGISTRY
from app.agents.registry import get_agent, normalize_agent_id
from app.agents.orchestrator import OrchestratorAgent, orchestrator_agent

AGENT_REGISTRY: Dict[str, BaseAgent] = {
    **EXECUTION_AGENT_REGISTRY,
    "orchestrator": orchestrator_agent,
}


__all__ = [
    "BaseAgent",
    "OrchestratorAgent",
    "orchestrator_agent",
    "CommunicationAgent",
    "communication_agent",
    "DocumentAgent",
    "document_agent",
    "FileManagerAgent",
    "file_manager_agent",
    "ResearchAgent",
    "research_agent",
    "BrowserAutomationAgent",
    "browser_agent",
    "ShoppingBookingAgent",
    "shopping_booking_agent",
    "VerificationAgent",
    "verification_agent",
    "AGENT_REGISTRY",
    "EXECUTION_AGENT_REGISTRY",
    "get_agent",
    "normalize_agent_id",
]
