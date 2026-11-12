"""Document Generation Agent Module."""

from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.document")


class DocumentAgent(BaseAgent):
    """Responsible for creating beautifully formatted PDF, DOCX, TXT, and Excel documents."""

    name = "Document Agent"
    description = "Formats and generates professional reports and documents in the authorized user workspace."
    system_prompt = "You are the Document Specialist for ORIGIN AI. Generate structured, professional publications."
    allowed_tools = ["create_pdf", "create_docx", "create_txt", "create_excel"]

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_id = step.tool_id or "create_pdf"
        params = dict(step.input_params)

        # Pull synthesized sections from research if not explicitly provided
        research_data = state.agent_outputs.get("research", {})
        sections = params.get("sections", [])
        if not sections and "report_sections" in research_data:
            sections = research_data["report_sections"]
            params["sections"] = sections

        # If sections is still empty, supply default sections
        if not sections and tool_id in ("create_pdf", "create_docx"):
            params["sections"] = [
                {
                    "heading": "1. Overview",
                    "content": f"Executive summary and analysis regarding: {state.user_command}.",
                },
                {
                    "heading": "2. Detailed Analysis",
                    "content": "Key insights, methodologies, and operational steps prepared by ORIGIN AI.",
                },
            ]

        # Execute registered document tool
        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error}

        file_data = result.data or {}
        return {
            "tool_id": tool_id,
            "filename": file_data.get("filename"),
            "file_path": file_data.get("file_path"),
            "file_size_bytes": file_data.get("file_size_bytes"),
            "sha256": file_data.get("sha256"),
            "file_id": file_data.get("file_id"),
        }

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


document_agent = DocumentAgent()

