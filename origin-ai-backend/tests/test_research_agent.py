import pytest
from pydantic import BaseModel

from app.agents.verifier import VerificationAgent
from app.graphs.state import OriginState, PlanStep
from app.agents.research import (
    REPORT_HEADINGS,
    ResearchAgent,
    ResearchSynthesis,
    ReportSection,
    SectionRepairOutput,
    SummaryRepairOutput,
)
from app.services.llm_service import LLMService
from app.tools.research_tools import _DuckDuckGoResultsParser


def test_search_results_parser_extracts_title_url_and_excerpt():
    parser = _DuckDuckGoResultsParser()
    parser.feed(
        '<div class="result">'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpaper">'
        "Research paper</a>"
        '<div class="result__snippet">An actual search excerpt.</div>'
        "</div>"
    )

    assert parser.results == [
        {
            "title": "Research paper",
            "url": "https://example.com/paper",
            "snippet": "An actual search excerpt.",
        }
    ]


def test_search_results_parser_extracts_anchor_excerpts():
    parser = _DuckDuckGoResultsParser()
    parser.feed(
        '<div class="result results_links"><a class="result__a" '
        'href="https://example.com/paper">Research paper</a>'
        '<a class="result__snippet" href="https://example.com/paper">'
        "A current DuckDuckGo excerpt.</a></div>"
    )

    assert parser.results[0]["snippet"] == "A current DuckDuckGo excerpt."


def test_synthesis_sections_are_canonicalized_and_reordered_without_changing_content():
    sections = [
        {"heading": heading, "content": f"Evidence for {heading}."}
        for heading in reversed(REPORT_HEADINGS)
    ]

    canonical = ResearchAgent._canonicalize_sections(sections)

    assert [section["heading"] for section in canonical] == list(REPORT_HEADINGS)
    assert canonical[0]["content"] == "Evidence for Executive Summary."


@pytest.mark.asyncio
async def test_uncited_section_is_revised_only_from_collected_evidence(monkeypatch):
    from app.services.llm_service import llm_service

    content = (
        "Collected evidence explains agent design, its implementation constraints, "
        "and the limits of the available search excerpts in this specific topic. "
    ) * 5
    content_with_citation = f"{content} [1]"
    initial_sections = [
        ReportSection(
            heading=heading,
            content=content if heading == "Conclusion" else content_with_citation,
        )
        for heading in REPORT_HEADINGS
    ]
    synthesis = ResearchSynthesis(
        summary=f"{content} [1]",
        key_findings=[f"Evidence-based finding {index} describes collected material. [1]" for index in range(6)],
        sections=initial_sections,
    )
    repaired_content = content_with_citation
    call_count = 0

    async def generate(prompt, response_model, system_prompt=None):
        nonlocal call_count
        call_count += 1
        if response_model is ResearchSynthesis:
            return synthesis
        assert response_model is SectionRepairOutput
        return SectionRepairOutput(
            sections=[
                ReportSection(heading="Conclusion", content=repaired_content)
            ]
        )

    monkeypatch.setattr(llm_service, "generate_structured", generate)
    sources = [
        {
            "citation_id": index,
            "title": f"Source {index}",
            "url": f"https://example.org/{index}",
            "content": f"Evidence excerpt {index}.",
            "matched_queries": ["topic"],
        }
        for index in range(1, 4)
    ]

    result = await ResearchAgent()._synthesize("topic", sources)

    assert call_count == 2
    assert "[1]" in result["sections"][-2]["content"]
    assert result["sections"][-1]["heading"] == "References"


@pytest.mark.asyncio
async def test_uncited_summary_and_findings_are_revised_from_collected_evidence(monkeypatch):
    from app.services.llm_service import llm_service

    content = (
        "Collected source excerpts describe the topic's design, practical constraints, "
        "and evidence limitations without establishing unsupported conclusions. "
    ) * 5
    synthesis = ResearchSynthesis(
        summary=content,
        key_findings=[f"Finding {index} based on collected source excerpts." for index in range(6)],
        sections=[
            ReportSection(heading=heading, content=f"{content} [1]")
            for heading in REPORT_HEADINGS
        ],
    )
    repaired_summary = f"{content} [1]"
    repaired_findings = [
        f"Finding {index} is supported by the collected source excerpt [1]."
        for index in range(1, 7)
    ]
    call_count = 0

    async def generate(prompt, response_model, system_prompt=None):
        nonlocal call_count
        call_count += 1
        if response_model is ResearchSynthesis:
            return synthesis
        assert response_model is SummaryRepairOutput
        return SummaryRepairOutput(
            summary=repaired_summary,
            key_findings=repaired_findings,
        )

    monkeypatch.setattr(llm_service, "generate_structured", generate)
    sources = [
        {
            "citation_id": index,
            "title": f"Source {index}",
            "url": f"https://example.org/{index}",
            "content": f"Evidence excerpt {index}.",
            "matched_queries": ["topic"],
        }
        for index in range(1, 4)
    ]

    result = await ResearchAgent()._synthesize("topic", sources)

    assert call_count == 2
    assert "[1]" in result["summary"]
    assert all("[1]" in finding for finding in result["findings"])


@pytest.mark.asyncio
async def test_search_response_normalization_deduplicates_and_maps_queries(monkeypatch):
    from app.tools.base import ToolResult
    from app.tools.registry import tool_registry

    async def search(tool_id, params, context=None):
        query = params["query"]
        source_index = {
            "first query": 1,
            "second query": 2,
            "extra query 0": 3,
        }.get(query, 2)
        payload = {
            "data": {
                "results": [
                    {
                        "title": f"Source {source_index}",
                        "url": f"https://example.org/{source_index}?tracking={query}",
                        "excerpt": f"Actual collected evidence for {query}.",
                    },
                    {
                        "title": "Shared source",
                        "link": "https://example.org/shared",
                        "text": "Shared collected evidence across search topics.",
                    },
                ]
            }
        }
        return ToolResult(success=True, data=payload)

    monkeypatch.setattr(tool_registry, "execute", search)
    queries = ["first query", "second query", *[f"extra query {i}" for i in range(6)]]
    sources = await ResearchAgent()._search_queries(queries)

    shared = next(source for source in sources if source["url"] == "https://example.org/shared")
    assert len(sources) == 4
    assert shared["matched_queries"] == queries
    assert all(source["content"] for source in sources)


@pytest.mark.asyncio
async def test_structured_groq_failure_is_not_replaced_by_fallback(caplog):
    class ResponseModel(BaseModel):
        answer: str

    class FailingGroqClient:
        def with_structured_output(self, *args, **kwargs):
            raise RuntimeError("404 model not found")

    service = LLMService.__new__(LLMService)
    service.primary_model = "openai/gpt-oss-120b"
    service._groq_client = FailingGroqClient()
    service._initialization_error = None

    with pytest.raises(RuntimeError, match="404 model not found"):
        await service.generate_structured("test", ResponseModel)

    assert "Groq structured generation failed" in caplog.text


@pytest.mark.asyncio
async def test_verifier_rejects_empty_research_and_report():
    state = OriginState(
        task_id="test",
        user_command="Research a topic and generate a report",
        execution_plan=[
            PlanStep(
                step_number=1,
                agent_name="research",
                action="Research topic",
                tool_id="web_search",
                status="COMPLETED",
            ),
            PlanStep(
                step_number=2,
                agent_name="document",
                action="Create PDF",
                tool_id="create_pdf",
                status="COMPLETED",
            ),
        ],
    )

    evidence = await VerificationAgent().verify_task(state)

    assert evidence["all_steps_successful"] is False
    assert evidence["research_valid"] is False
    assert evidence["documents_valid"] is False
    assert evidence["discrepancies"]
