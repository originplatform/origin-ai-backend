import uuid
from pathlib import Path

import pytest

from app.agents.document import DocumentAgent, DocumentDraft, GeneratedSection
from app.agents.orchestrator import (
    DOCUMENT_FORMAT_TO_TOOL,
    OrchestratorAgent,
    detect_execution_requirements,
)
from app.agents.research import REPORT_HEADINGS, ResearchAgent
from app.agents.verifier import VerificationAgent
from app.graphs.nodes import execute_step_node
from app.graphs.state import OriginState, PlanStep
from app.agents.file_manager import file_manager_agent
from app.graphs.state import PlanStep as StatePlanStep
from app.tools.base import ToolResult
from app.tools.registry import tool_registry


DOCUMENT_ONLY_COMMAND = (
    "Create a professional DOCX and PDF report explaining Python programming "
    "fundamentals and save both files in my workspace."
)
RESEARCH_COMMAND = (
    "Research autonomous AI agents using reliable web sources, create a "
    "professional DOCX and PDF report, and save both files in my workspace."
)


def test_verifier_matches_source_urls_split_by_pdf_line_wrapping():
    wrapped_text = "References\nhttps://www.example.org/a/long-\npath?query=value"

    assert VerificationAgent._contains_url(
        wrapped_text,
        "https://www.example.org/a/long-path?query=value",
    )


def _document_draft():
    paragraphs = (
        "This section explains the topic with concrete concepts, operational details, "
        "and a practical example. It distinguishes essential terminology, describes "
        "how the ideas relate, and notes constraints that affect real implementations. "
    ) * 5
    return DocumentDraft(
        title="Python Programming Fundamentals",
        subtitle="A practical technical introduction",
        sections=[
            GeneratedSection(heading=f"Topic {index}", content=paragraphs)
            for index in range(1, 7)
        ],
    )


def _research_state(command, formats):
    queries = [f"focused research query {index}" for index in range(1, 9)]
    sources = [
        {
            "citation_id": index,
            "title": f"Source {index}",
            "url": f"https://research.example.org/{index}",
            "content": f"Source excerpt {index} with technical evidence.",
            "matched_queries": [queries[index - 1]],
        }
        for index in range(1, 4)
    ]
    body = (
        "Collected research describes the system architecture, major components, "
        "design trade-offs, evaluation considerations, and operational constraints "
        "with evidence linked to the retrieved sources. [1] [2] [3]. "
    ) * 5
    sections = [
        {"heading": heading, "content": body}
        for heading in REPORT_HEADINGS
    ]
    sections.append(
        {
            "heading": "References",
            "content": "\n".join(
                f"[{source['citation_id']}] {source['title']}. {source['url']}"
                for source in sources
            ),
        }
    )
    plan = [
        PlanStep(
            step_number=1,
            agent_name="research",
            action="Research the requested topic",
            tool_id="web_search",
            status="COMPLETED",
        )
    ]
    for step_number, file_format in enumerate(formats, start=2):
        tool_id = DOCUMENT_FORMAT_TO_TOOL[file_format]
        plan.append(
            PlanStep(
                step_number=step_number,
                agent_name="document",
                action=f"Create {file_format}",
                tool_id=tool_id,
                dependencies=[1],
            )
        )
    plan.append(
        PlanStep(
            step_number=len(plan) + 1,
            agent_name="verification",
            action="Verify research and documents",
            dependencies=[step.step_number for step in plan],
        )
    )
    return OriginState(
        task_id=str(uuid.uuid4()),
        user_command=command,
        execution_plan=plan,
        research_queries=queries,
        research_sources=sources,
        research_findings=[
            f"Finding {index}: collected evidence supports this technical observation [1] [2]."
            for index in range(1, 7)
        ],
        research_summary=body,
        report_sections=sections,
        document_title="Autonomous AI Agents",
    )


def _document_only_state(formats):
    plan = [
        PlanStep(
            step_number=index,
            agent_name="document",
            action=f"Create {file_format}",
            tool_id=DOCUMENT_FORMAT_TO_TOOL[file_format],
        )
        for index, file_format in enumerate(formats, start=1)
    ]
    plan.append(
        PlanStep(
            step_number=len(plan) + 1,
            agent_name="verification",
            action="Verify outputs",
            dependencies=[step.step_number for step in plan],
        )
    )
    return OriginState(
        task_id=str(uuid.uuid4()),
        user_command=DOCUMENT_ONLY_COMMAND,
        execution_plan=plan,
    )


@pytest.mark.parametrize(
    ("command", "formats", "research_required"),
    [
        ("Create a DOCX explaining Python basics.", ["docx"], False),
        ("Create a PDF explaining Python basics.", ["pdf"], False),
        ("Create a DOCX and PDF explaining Python basics.", ["docx", "pdf"], False),
        ("Research Python basics and create a DOCX.", ["docx"], True),
        ("Research Python basics and create a PDF.", ["pdf"], True),
        ("Research Python basics and create a DOCX and PDF.", ["docx", "pdf"], True),
    ],
)
def test_intent_detection_builds_only_required_research_steps(
    command,
    formats,
    research_required,
):
    requirements = detect_execution_requirements(command)
    plan = OrchestratorAgent._build_required_plan(command, requirements)

    assert requirements["formats"] == formats
    assert requirements["research_required"] is research_required
    assert [step.agent_name for step in plan.steps] == (
        (["research"] if research_required else [])
        + ["document"] * len(formats)
        + ["verification"]
    )
    assert ("web_search" in plan.selected_tools) is research_required
    assert all(
        step.dependencies == ([1] if research_required else [])
        for step in plan.steps
        if step.agent_name == "document"
    )


@pytest.mark.asyncio
async def test_empty_web_search_results_are_rejected_without_fabrication(monkeypatch):
    async def empty_search(*args, **kwargs):
        return ToolResult(success=True, data={"results": []})

    monkeypatch.setattr(tool_registry, "execute", empty_search)
    with pytest.raises(ValueError, match="Only 0 unique sources"):
        await ResearchAgent()._search_queries([f"query {index}" for index in range(8)])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formats", "research_required"),
    [
        (["docx"], False),
        (["pdf"], False),
        (["docx", "pdf"], False),
        (["docx"], True),
        (["pdf"], True),
        (["docx", "pdf"], True),
    ],
)
async def test_requested_documents_are_created_and_content_is_verified(
    monkeypatch,
    formats,
    research_required,
):
    from app.services.llm_service import llm_service

    async def generate_document(*args, **kwargs):
        response_model = kwargs["response_model"]
        if response_model is DocumentDraft:
            return _document_draft()
        raise AssertionError(f"Unexpected structured output model: {response_model}")

    monkeypatch.setattr(llm_service, "generate_structured", generate_document)
    state = (
        _research_state(RESEARCH_COMMAND, formats)
        if research_required
        else _document_only_state(formats)
    )
    agent = DocumentAgent()

    for step in state.execution_plan:
        if step.agent_name != "document":
            continue
        step.input_params["filename"] = f"{uuid.uuid4().hex}.{step.tool_id.removeprefix('create_')}"
        output = await agent.execute_step(step, state)
        assert output.get("file_path")
        step.status = "COMPLETED"
        step.output = output

    evidence = await VerificationAgent().verify_task(state)
    assert evidence["documents_valid"] is True, evidence
    assert evidence["all_steps_successful"] is True
    assert {output["format"] for output in state.document_outputs} == set(formats)
    assert all(output in state.generated_files for output in state.document_outputs)
    assert all(
        len(VerificationAgent._extract_document_text(Path(output["file_path"])).split())
        >= (500 if research_required else 300)
        for output in state.document_outputs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_id", "file_format"), [("create_docx", "docx"), ("create_pdf", "pdf")])
async def test_document_tool_failures_are_reported(monkeypatch, tool_id, file_format):
    from app.services.llm_service import llm_service

    async def generate_document(*args, **kwargs):
        return _document_draft()

    async def fail_document(tool_id_arg, params, context=None):
        return ToolResult(success=False, error=f"{tool_id_arg} write failed")

    monkeypatch.setattr(llm_service, "generate_structured", generate_document)
    monkeypatch.setattr(tool_registry, "execute", fail_document)
    state = _document_only_state([file_format])

    output = await DocumentAgent().execute_step(state.execution_plan[0], state)

    assert output == {"error": f"{tool_id} write failed"}
    assert not state.document_outputs


@pytest.mark.asyncio
async def test_one_format_can_succeed_when_another_document_tool_fails(monkeypatch):
    from app.services.llm_service import llm_service

    async def generate_document(*args, **kwargs):
        return _document_draft()

    real_execute = tool_registry.execute

    async def fail_pdf(tool_id, params, context=None):
        if tool_id == "create_pdf":
            return ToolResult(success=False, error="PDF renderer failed")
        return await real_execute(tool_id, params, context)

    monkeypatch.setattr(llm_service, "generate_structured", generate_document)
    monkeypatch.setattr(tool_registry, "execute", fail_pdf)
    state = _document_only_state(["docx", "pdf"])
    state.execution_plan[0].input_params["filename"] = f"{uuid.uuid4().hex}.docx"

    docx_output = await DocumentAgent().execute_step(state.execution_plan[0], state)
    state.execution_plan[0].status = "COMPLETED"
    state.execution_plan[0].output = docx_output
    pdf_output = await DocumentAgent().execute_step(state.execution_plan[1], state)
    state.execution_plan[1].status = "FAILED"
    state.execution_plan[1].error = pdf_output["error"]

    evidence = await VerificationAgent().verify_task(state)
    assert docx_output.get("file_path")
    assert "PDF renderer failed" in pdf_output["error"]
    assert evidence["documents_valid"] is False
    assert evidence["all_steps_successful"] is False


@pytest.mark.asyncio
async def test_failed_research_dependency_marks_document_step_skipped():
    state = OriginState(
        task_id=str(uuid.uuid4()),
        user_command=RESEARCH_COMMAND,
        execution_plan=[
            PlanStep(
                step_number=1,
                agent_name="research",
                action="Research sources",
                tool_id="web_search",
                status="FAILED",
                error="No usable search results",
            ),
            PlanStep(
                step_number=2,
                agent_name="document",
                action="Create DOCX",
                tool_id="create_docx",
                dependencies=[1],
            ),
            PlanStep(
                step_number=3,
                agent_name="verification",
                action="Verify outputs",
                dependencies=[1, 2],
            ),
        ],
    )

    updated = await execute_step_node(state)

    assert updated.execution_plan[1].status == "SKIPPED"
    assert not updated.document_outputs
    assert not updated.generated_files


@pytest.mark.asyncio
async def test_file_conversion_reads_source_before_creating_target():
    from app.tools.registry import tool_registry

    source_name = f"conversion-{uuid.uuid4().hex}.txt"
    source_text = "A real source document that must be preserved during conversion."
    created = await tool_registry.execute(
        "create_txt",
        {"filename": source_name, "content": source_text},
    )
    assert created.success

    command = f"Convert {source_name} to PDF."
    requirements = detect_execution_requirements(command)
    plan_output = OrchestratorAgent._build_required_plan(command, requirements)
    state = OriginState(
        task_id=str(uuid.uuid4()),
        user_command=command,
        execution_plan=[
            StatePlanStep.model_validate(step.model_dump())
            for step in plan_output.steps
        ],
        document_conversion=True,
    )

    read_step = state.execution_plan[0]
    source_data = await file_manager_agent.execute_step(read_step, state)
    state.source_document_content = source_data["content"]
    read_step.status = "COMPLETED"
    state.execution_plan[1].input_params["filename"] = f"converted-{uuid.uuid4().hex}.pdf"
    output = await DocumentAgent().execute_step(state.execution_plan[1], state)
    state.execution_plan[1].status = "COMPLETED"
    state.execution_plan[1].output = output

    evidence = await VerificationAgent().verify_task(state)
    assert requirements["conversion_required"] is True
    assert [step.tool_id for step in plan_output.steps] == [
        "read_document",
        "create_pdf",
        None,
    ]
    assert source_text in VerificationAgent._extract_document_text(Path(output["file_path"]))
    assert evidence["documents_valid"] is True, evidence["discrepancies"]
