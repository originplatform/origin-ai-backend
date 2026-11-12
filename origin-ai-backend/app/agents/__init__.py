"""Agents package and unified lookup directory."""

from typing import Dict
from app.agents.base import BaseAgent
from app.agents.orchestrator import OrchestratorAgent, orchestrator_agent
from app.agents.communication import CommunicationAgent, communication_agent
from app.agents.document import DocumentAgent, document_agent
from app.agents.file_manager import FileManagerAgent, file_manager_agent
from app.agents.research import ResearchAgent, research_agent
from app.agents.browser import BrowserAutomationAgent, browser_agent
from app.agents.shopping_booking import ShoppingBookingAgent, shopping_booking_agent
from app.agents.verifier import VerificationAgent, verification_agent

AGENT_REGISTRY: Dict[str, BaseAgent] = {
    "Orchestrator Agent": orchestrator_agent,
    "Communication Agent": communication_agent,
    "Document Agent": document_agent,
    "File Management Agent": file_manager_agent,
    "Research Agent": research_agent,
    "Browser Automation Agent": browser_agent,
    "Shopping and Booking Agent": shopping_booking_agent,
    "Verification Agent": verification_agent,
}


def get_agent(name: str) -> BaseAgent:
    """Retrieves agent instance by name or defaults to orchestrator."""
    return AGENT_REGISTRY.get(name, orchestrator_agent)


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
    "get_agent",
]

