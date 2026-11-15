"""Document Generation Agent Module."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.agents.base import BaseAgent
from app.core.security import PathSecurity
from app.graphs.state import OriginState, PlanStep
from app.services.llm_service import llm_service
from app.tools.registry import tool_registry

DOCUMENT_ONLY_MIN_WORDS = 300


class GeneratedSection(BaseModel):
    heading: str
    content: str


class DocumentDraft(BaseModel):
    title: str
    subtitle: str = ""
    sections: List[GeneratedSection]


class DocumentAgent(BaseAgent):
    """Generates documents from collected research or a direct explanatory request."""

    name = "Document Agent"
    description = "Generates professional reports from research or the user's direct request."
    system_prompt = (
        "You are the ORIGIN AI Document Specialist. For research-backed reports, use only the supplied "
        "research content. For document-only tasks, explain the user's topic from general model knowledge, "
        "do not claim web research, and do not invent citations or references."
    )
    allowed_tools = ["create_pdf", "create_docx", "create_txt", "create_excel"]

    @staticmethod
    def _research_required(state: OriginState) -> bool:
        from app.agents.registry import normalize_agent_id

        return any(
            normalize_agent_id(step.agent_name) == "research"
            for step in state.execution_plan
        )

    @staticmethod
    def _fallback_title(command: str) -> str:
        title = re.sub(
            r"^(?:please\s+)?(?:research|create|generate|write)\s+",
            "",
            command.strip(),
            flags=re.IGNORECASE,
        )
        title = re.split(r"\b(?:and\s+)?save\b", title, maxsplit=1, flags=re.IGNORECASE)[0]
        title = re.sub(
            r"\b(?:professional\s+)?(?:docx|pdf|txt|xlsx|excel|spreadsheet)\b",
            "",
            title,
            flags=re.I,
        )
        title = re.sub(r"\b(?:report|document|file)\b", "", title, flags=re.I)
        title = re.sub(r"\s+", " ", title).strip(" .,:;-'")
        return title[:120].title() or "ORIGIN AI Report"

    async def _generate_document_only_sections(self, state: OriginState) -> None:
        response = await llm_service.generate_structured(
            prompt=(
                f"Create a professional, technically accurate explanatory report for this request:\n"
                f"{state.user_command}\n\n"
                "This is a document-only task, not web research. Use general model knowledge without claiming "
                "that sources were searched; do not fabricate citations, quotes, or a reference list. "
                "Choose a concise descriptive title and 6 to 10 useful headings tailored to the requested topic. "
                "Write at least 50 substantive words per section and at least 300 words overall. "
                "Include practical explanations or examples where useful, and clearly qualify uncertainty."
            ),
            response_model=DocumentDraft,
            system_prompt=self.system_prompt,
        )
        sections = [section.model_dump() for section in response.sections]
        total_words = sum(len(section["content"].split()) for section in sections)
        if len(sections) < 5 or any(
            len(section["content"].split()) < 40 for section in sections
        ):
            raise ValueError("Document content generation returned too few substantive sections.")
        if total_words < DOCUMENT_ONLY_MIN_WORDS:
            raise ValueError(
                f"Document content generation returned {total_words} words; "
                f"at least {DOCUMENT_ONLY_MIN_WORDS} are required."
            )
        state.document_title = response.title.strip()
        state.report_sections = sections

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_id = step.tool_id
        if not tool_id:
            return {"error": "Document step does not specify a registered output tool."}

        research_required = self._research_required(state)
        if state.document_conversion:
            if not state.source_document_content.strip():
                return {"error": "Source document was not read or contained no readable text."}
            if not state.report_sections:
                state.report_sections = [
                    {
                        "heading": "Converted Content",
                        "content": state.source_document_content,
                    }
                ]
            if not state.document_title:
                source_step = next(
                    (
                        item for item in state.execution_plan
                        if item.tool_id == "read_document"
                    ),
                    None,
                )
                source_name = Path(
                    str((source_step.input_params if source_step else {}).get("filename_or_path") or "")
                ).stem
                state.document_title = source_name.replace("_", " ").title() or "Converted Document"
        if research_required and (
            not state.research_findings or not state.research_sources or not state.report_sections
        ):
            return {
                "error": (
                    "Research findings, sources, and substantive report sections are required "
                    "before document generation."
                )
            }
        if not state.report_sections and not state.document_conversion:
            await self._generate_document_only_sections(state)

        planned_title = str(step.input_params.get("title") or "").strip()
        if planned_title.casefold() == state.user_command.strip().casefold():
            planned_title = ""
        title = state.document_title or planned_title or self._fallback_title(state.user_command)
        state.document_title = title
        params = dict(step.input_params)
        params["title"] = title
        if tool_id in {"create_pdf", "create_docx"}:
            params["sections"] = state.report_sections
        elif tool_id == "create_txt":
            params["content"] = "\n\n".join(
                f"{section['heading']}\n{section['content']}"
                for section in state.report_sections
            )
        elif tool_id == "create_excel":
            params["headers"] = ["Section", "Content"]
            params["rows"] = [
                ["Title", title],
                *[
                    [section["heading"], section["content"]]
                    for section in state.report_sections
                ],
            ]

        result = await tool_registry.execute(tool_id, params, context)
        if not result.success:
            return {"error": result.error or f"Document tool '{tool_id}' failed."}

        file_data = result.data or {}
        raw_path = file_data.get("file_path")
        if not raw_path:
            return {"error": f"Document tool '{tool_id}' did not return an output path."}
        try:
            safe_path = PathSecurity.resolve_safe_path(
                str(raw_path),
                allow_create_parent=False,
            )
            expected_extension = {
                "create_pdf": ".pdf",
                "create_docx": ".docx",
                "create_txt": ".txt",
                "create_excel": ".xlsx",
            }[tool_id]
            if safe_path.suffix.casefold() != expected_extension:
                raise ValueError(
                    f"Expected a {expected_extension} output, got '{safe_path.suffix}'."
                )
            file_size = PathSecurity.validate_file_size(safe_path)
            if file_size <= 0:
                raise ValueError("Generated document is empty.")
        except Exception as exc:
            return {"error": f"Generated document failed output validation: {exc}"}

        output = {
            "tool_id": tool_id,
            "format": {
                "create_pdf": "pdf",
                "create_docx": "docx",
                "create_txt": "txt",
                "create_excel": "xlsx",
            }[tool_id],
            "title": title,
            "filename": file_data.get("filename") or safe_path.name,
            "file_path": str(safe_path),
            "file_size_bytes": file_size,
            "sha256": file_data.get("sha256"),
            "file_id": file_data.get("file_id"),
            "section_count": len(state.report_sections),
            "word_count": sum(
                len(section["content"].split()) for section in state.report_sections
            ),
        }
        state.document_outputs.append(output)
        state.generated_files.append(output)
        return output

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        return state


document_agent = DocumentAgent()
