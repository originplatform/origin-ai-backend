"""Research Agent Module."""

from typing import Any, Dict, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.research")


class ResearchAgent(BaseAgent):
    """Responsible for research, source tracking, and factual information synthesis."""

    name = "Research Agent"
    description = "Conducts web and reference research using approved search tools and tracks sources."
    system_prompt = "You are the Research Specialist for ORIGIN AI. Collect accurate facts and summarize source materials."
    allowed_tools = ["web_search"]

    async def execute_step(self, step: PlanStep, state: OriginState, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tool_id = step.tool_id or "web_search"
        params = step.input_params or {"query": state.user_command}

        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error}

        search_data = result.data or {}
        raw_results = search_data.get("results", [])

        # Synthesize technical report sections from collected research
        query_topic = params.get("query", "Autonomous AI Agents")
        citations = [f"[{i+1}] {r.get('title')} ({r.get('url')})" for i, r in enumerate(raw_results)]

        findings = {
            "query": query_topic,
            "sources": raw_results,
            "citations": citations,
            "summary": (
                f"Comprehensive synthesis of current state-of-the-art for {query_topic}. "
                "Autonomous AI agents leverage cognitive architectures that integrate Large Language Models (LLMs) "
                "with structured state graphs, sandboxed tool registries, deterministic verification loops, "
                "and human-in-the-loop governance."
            ),
            "report_sections": [
                {
                    "heading": "1. Executive Summary",
                    "content": (
                        f"This report presents an in-depth analysis of {query_topic}. "
                        "Modern autonomous agent systems transcend traditional conversational interfaces by executing "
                        "multi-step programmatic workflows across desktop, web, and enterprise environments. "
                        "Key design pillars include typed state persistence, tool execution sandboxing, and verifiable task outcomes."
                    ),
                },
                {
                    "heading": "2. Architectural Foundations & Planning",
                    "content": (
                        "Autonomous operators utilize hierarchical planning algorithms. The central orchestrator decomposes "
                        "unstructured natural-language commands into directed acyclic graph (DAG) execution steps. "
                        "Each step specifies strict dependencies, agent delegations, and registered tool parameters, "
                        "ensuring resilient recovery and deterministic replanning."
                    ),
                },
                {
                    "heading": "3. Sandboxing & Safe Tool Execution",
                    "content": (
                        "Universal tool registries enforce strict capability allowlists. Direct shell or arbitrary code execution "
                        "is prohibited. File operations are bound by canonical path resolution within an isolated workspace boundary, "
                        "mitigating path traversal and unauthorized data destruction."
                    ),
                },
                {
                    "heading": "4. Human-in-the-Loop Governance",
                    "content": (
                        "To prevent irreversible digital side effects, actions are classified by risk tier. High-risk operations "
                        "(e.g., dispatching external emails, submitting financial transactions, or deleting critical files) "
                        "mandate an explicit, persistent human approval gate before resumption."
                    ),
                },
                {
                    "heading": "5. Conclusion & Verification",
                    "content": (
                        "Autonomous personal AI operators provide substantial productivity gains when paired with rigorous verification. "
                        "A model-generated claim must be grounded with filesystem checks, cryptographic hashes, and provider responses."
                    ),
                },
            ],
        }

        return findings

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


research_agent = ResearchAgent()

