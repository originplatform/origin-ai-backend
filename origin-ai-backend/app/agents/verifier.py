"""Verification Agent for research quality and generated document contents."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.core.security import PathSecurity
from app.graphs.state import OriginState, PlanStep

logger = get_logger("origin.agents.verifier")
DOCUMENT_ONLY_MIN_WORDS = 300

REQUIRED_REPORT_HEADINGS = {
    "executive summary",
    "introduction and background",
    "core concepts and technical architecture",
    "planning and reasoning",
    "memory and tool calling",
    "multi-agent systems and frameworks",
    "detailed topic-wise analysis",
    "practical applications and examples",
    "benefits and limitations",
    "security and challenges",
    "future scope",
    "conclusion",
    "references",
}


class VerificationAgent(BaseAgent):
    """Checks research, citations, report quality, and readable output contents."""

    name = "Verification Agent"
    description = "Validates evidence, report quality, citations, and generated document contents."
    system_prompt = "You are the Verification Specialist for ORIGIN AI. Verify observable evidence, not claims."
    allowed_tools: List[str] = []

    @staticmethod
    def _extract_document_text(path: Path) -> str:
        if path.suffix.casefold() == ".docx":
            from docx import Document

            document = Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        if path.suffix.casefold() == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if path.suffix.casefold() == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                return "\n".join(
                    str(value)
                    for sheet in workbook.worksheets
                    for row in sheet.iter_rows(values_only=True)
                    for value in row
                    if value is not None
                )
            finally:
                workbook.close()
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _normalized(text: str) -> str:
        return re.sub(r"\s+", " ", text).casefold()

    @staticmethod
    def _contains_url(text: str, url: str) -> bool:
        compact_text = re.sub(r"\s+", "", text).casefold()
        compact_url = re.sub(r"\s+", "", url).casefold()
        return bool(compact_url) and compact_url in compact_text

    @staticmethod
    def _planned_document_formats(state: OriginState) -> Set[str]:
        return {
            {
                "create_pdf": "pdf",
                "create_docx": "docx",
                "create_txt": "txt",
                "create_excel": "xlsx",
            }[step.tool_id]
            for step in state.execution_plan
            if step.tool_id in {"create_pdf", "create_docx", "create_txt", "create_excel"}
        }

    async def verify_task(
        self,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.agents.registry import normalize_agent_id

        discrepancies: List[str] = []
        expected_formats = self._planned_document_formats(state)
        research_required = any(
            normalize_agent_id(step.agent_name) == "research"
            for step in state.execution_plan
        )

        evidence: Dict[str, Any] = {
            "verified_files": [],
            "verified_drafts": [],
            "completed_steps": 0,
            "total_steps": len(state.execution_plan),
            "research_valid": not research_required,
            "sources_relevant": not research_required,
            "report_valid": not research_required,
            "citations_valid": not research_required,
            "documents_valid": not expected_formats,
            "document_word_count": 0,
            "all_steps_successful": True,
            "discrepancies": discrepancies,
        }

        for step in state.execution_plan:
            if normalize_agent_id(step.agent_name) == "verification":
                continue
            if step.status == "COMPLETED":
                evidence["completed_steps"] += 1
            else:
                evidence["all_steps_successful"] = False
                discrepancies.append(
                    f"Step {step.step_number} ({step.action}) ended with status '{step.status}': {step.error}"
                )

        source_ids = {
            int(source["citation_id"])
            for source in state.research_sources
            if str(source.get("citation_id", "")).isdigit()
        }
        source_records_valid = len(state.research_sources) >= 3 and all(
            source.get("title")
            and source.get("content")
            and urlparse(str(source.get("url") or "")).scheme in {"http", "https"}
            and urlparse(str(source.get("url") or "")).netloc
            for source in state.research_sources
        )
        query_count_valid = 6 <= len(state.research_queries) <= 10
        findings_valid = len(state.research_findings) >= 6 and all(
            isinstance(finding, str) and len(finding.split()) >= 8
            for finding in state.research_findings
        )
        if research_required:
            evidence["research_valid"] = (
                query_count_valid
                and source_records_valid
                and findings_valid
                and len(state.research_summary.split()) >= 50
            )
            if not query_count_valid:
                discrepancies.append(
                    f"Expected 6-10 focused research queries; found {len(state.research_queries)}."
                )
            if not source_records_valid:
                discrepancies.append("Research must contain at least 3 unique sources with title, URL, and content.")
            if not findings_valid or len(state.research_summary.split()) < 50:
                discrepancies.append("Research findings or summary are empty or too short.")

            query_set = set(state.research_queries)
            evidence["sources_relevant"] = source_records_valid and all(
                bool(set(source.get("matched_queries", [])) & query_set)
                for source in state.research_sources
            )
            if not evidence["sources_relevant"]:
                discrepancies.append("One or more collected sources are not tied to a research query.")

            headings = {
                str(section.get("heading", "")).strip().casefold()
                for section in state.report_sections
            }
            content_sections = [
                section for section in state.report_sections
                if str(section.get("heading", "")).strip().casefold() != "references"
            ]
            section_word_count = sum(
                len(str(section.get("content", "")).split()) for section in state.report_sections
            )
            evidence["report_valid"] = (
                REQUIRED_REPORT_HEADINGS.issubset(headings)
                and len(content_sections) >= 10
                and all(len(str(section.get("content", "")).split()) >= 40 for section in content_sections)
                and section_word_count >= 500
            )
            if not evidence["report_valid"]:
                discrepancies.append(
                    "Report sections are incomplete or not substantive "
                    f"({len(state.report_sections)} sections, {section_word_count} words)."
                )

            citation_ids = {
                int(citation)
                for section in state.report_sections
                for citation in re.findall(r"\[(\d+)\]", str(section.get("content", "")))
            }
            all_sections_cited = all(
                re.search(r"\[\d+\]", str(section.get("content", "")))
                for section in content_sections
            )
            references_section = next(
                (
                    str(section.get("content", ""))
                    for section in state.report_sections
                    if str(section.get("heading", "")).strip().casefold() == "references"
                ),
                "",
            )
            references_text = self._normalized(references_section)
            all_sources_referenced = all(
                f"[{source['citation_id']}]".casefold() in references_text
                and self._normalized(str(source["title"])) in references_text
                and self._normalized(str(source["url"])) in references_text
                for source in state.research_sources
            )
            evidence["citations_valid"] = (
                bool(citation_ids)
                and all_sections_cited
                and citation_ids.issubset(source_ids)
                and all_sources_referenced
            )
            if not evidence["citations_valid"]:
                discrepancies.append("Report citations or reference entries do not match collected sources.")

        document_outputs = state.document_outputs
        output_formats = {
            str(item.get("format") or Path(str(item.get("filename") or "")).suffix.lstrip(".")).casefold()
            for item in document_outputs
        }
        documents_valid = expected_formats.issubset(output_formats)
        document_only_report_valid = (
            len(state.report_sections) >= 5
            and all(
                len(str(section.get("content", "")).split()) >= 40
                for section in state.report_sections
            )
            and sum(
                len(str(section.get("content", "")).split())
                for section in state.report_sections
            ) >= 300
        )
        if (
            expected_formats
            and not research_required
            and not state.document_conversion
            and not document_only_report_valid
        ):
            documents_valid = False
            discrepancies.append(
                "Document-only content is missing or not substantive "
                f"({len(state.report_sections)} sections)."
            )
        for item in document_outputs:
            filename = str(item.get("filename") or "")
            if not filename:
                documents_valid = False
                discrepancies.append("A document output is missing its filename.")
                continue
            try:
                safe_path = PathSecurity.resolve_safe_path(
                    str(item.get("file_path") or filename),
                    allow_create_parent=False,
                )
                expected_format = str(item.get("format") or "").casefold()
                if expected_format not in expected_formats:
                    documents_valid = False
                    discrepancies.append(
                        f"Document '{filename}' has unexpected format '{expected_format}'."
                    )
                if safe_path.suffix.casefold() != f".{expected_format}":
                    documents_valid = False
                    discrepancies.append(
                        f"Document '{filename}' has an extension that does not match '{expected_format}'."
                    )
                if not safe_path.is_file() or safe_path.stat().st_size <= 0:
                    documents_valid = False
                    discrepancies.append(f"Document '{filename}' is missing or empty.")
                    continue
                text = self._extract_document_text(safe_path)
                word_count = len(text.split())
                evidence["document_word_count"] = max(evidence["document_word_count"], word_count)
                if research_required and word_count < 500:
                    documents_valid = False
                    discrepancies.append(
                        f"Document '{filename}' contains only {word_count} readable words; at least 500 are required."
                    )
                if (
                    not research_required
                    and not state.document_conversion
                    and word_count < DOCUMENT_ONLY_MIN_WORDS
                ):
                    documents_valid = False
                    discrepancies.append(
                        f"Document '{filename}' contains only {word_count} readable words; "
                        f"at least {DOCUMENT_ONLY_MIN_WORDS} are required."
                    )
                expected_title = self._normalized(str(item.get("title") or state.document_title))
                normalized_text = self._normalized(text)
                compact_title = re.sub(r"[^a-z0-9]", "", expected_title)
                compact_text = re.sub(r"[^a-z0-9]", "", normalized_text)
                if expected_title and expected_title not in normalized_text and not all(
                    term in normalized_text for term in expected_title.split()
                ) and compact_title not in compact_text:
                    documents_valid = False
                    discrepancies.append(f"Document '{filename}' does not contain its expected title.")
                if state.document_conversion and self._normalized(
                    state.source_document_content
                ) not in normalized_text:
                    documents_valid = False
                    discrepancies.append(
                        f"Converted document '{filename}' does not preserve readable source content."
                    )

                if research_required:
                    if not all(
                        heading in normalized_text
                        for heading in REQUIRED_REPORT_HEADINGS
                    ):
                        documents_valid = False
                        discrepancies.append(f"Document '{filename}' is missing required report sections.")
                    document_citations = {
                        int(citation) for citation in re.findall(r"\[(\d+)\]", text)
                    }
                    if not document_citations or not document_citations.issubset(source_ids):
                        documents_valid = False
                        discrepancies.append(f"Document '{filename}' contains missing or unknown citations.")
                    if not all(
                        self._contains_url(text, str(source["url"]))
                        for source in state.research_sources
                    ):
                        documents_valid = False
                        discrepancies.append(f"Document '{filename}' does not contain collected source URLs.")

                evidence["verified_files"].append(
                    {
                        "filename": filename,
                        "exists": True,
                        "size_bytes": safe_path.stat().st_size,
                        "verified_readable": bool(text.strip()),
                        "word_count": word_count,
                        "file_id": item.get("file_id"),
                    }
                )
            except Exception as exc:
                documents_valid = False
                discrepancies.append(f"Verification failed for '{filename}': {exc}")

        if expected_formats:
            evidence["documents_valid"] = documents_valid
            missing_formats = expected_formats - output_formats
            if missing_formats:
                discrepancies.append(
                    "Missing requested document formats: "
                    + ", ".join(sorted(missing_formats))
                )

        evidence["all_steps_successful"] = (
            evidence["all_steps_successful"]
            and evidence["research_valid"]
            and evidence["sources_relevant"]
            and evidence["report_valid"]
            and evidence["citations_valid"]
            and evidence["documents_valid"]
        )
        return evidence

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self.verify_task(state, context)

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        evidence = await self.verify_task(state, context)
        state.verification_evidence = evidence
        state.verification_results = evidence
        return state


verification_agent = VerificationAgent()
