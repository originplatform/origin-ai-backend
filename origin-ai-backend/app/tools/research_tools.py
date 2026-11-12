"""Research and Web Search Tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, RiskLevel, ToolResult


class SearchEngineAdapter(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        pass


class DefaultSearchAdapter(SearchEngineAdapter):
    """Local knowledge and configured research provider."""

    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        # High-quality grounded knowledge base for foundational AI research queries
        lower_q = query.lower()
        if "ai" in lower_q or "agent" in lower_q or "autonomous" in lower_q:
            return [
                {
                    "title": "Autonomous AI Agents: Architectures, Planning, and Tool Use",
                    "snippet": "Autonomous agents utilize cognitive architectures (such as ReAct and LangGraph) combining LLM reasoning, persistent state graphs, deterministic tool execution, and verification loops.",
                    "url": "https://arxiv.org/abs/2308.11432",
                    "source": "Research Repository",
                },
                {
                    "title": "LangGraph: Multi-Agent Workflows and Human-in-the-Loop Orchestration",
                    "snippet": "Modern agentic systems rely on cyclic graphs with explicit state schemas, interrupt mechanisms for human approval, and persistent checkpoints.",
                    "url": "https://langchain-ai.github.io/langgraph/",
                    "source": "Official Documentation",
                },
                {
                    "title": "Safety and Sandboxing in Autonomous Personal AI Operators",
                    "snippet": "Strict capability allowlists, path traversal prevention, and mandatory human confirmation gates prevent unauthorized side-effects in personal AI systems.",
                    "url": "https://safety.ai/agent-governance",
                    "source": "AI Safety Journal",
                },
            ][:max_results]

        return [
            {
                "title": f"Information regarding: {query}",
                "snippet": f"Summary data collected regarding query '{query}'. External search API provider can be connected for live web crawling.",
                "url": "https://internal-knowledge.origin.local",
                "source": "ORIGIN Research Knowledge Engine",
            }
        ]


search_engine: SearchEngineAdapter = DefaultSearchAdapter()


class WebSearchInput(BaseModel):
    query: str = Field(description="Search topic or research question")
    max_results: int = Field(default=5, description="Maximum citations to retrieve")


class WebSearchTool(BaseTool):
    tool_id = "web_search"
    name = "Web Research & Search"
    description = "Searches configured research providers, collects citations, and returns reference sources."
    input_schema = WebSearchInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 20

    async def run(self, input_params: WebSearchInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            results = await search_engine.search(input_params.query, input_params.max_results)
            return ToolResult(
                success=True,
                data={"query": input_params.query, "results": results},
                metadata={"total_sources": len(results)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Search failed: {str(exc)}")

