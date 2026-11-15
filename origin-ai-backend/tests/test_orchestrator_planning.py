import pytest

from app.agents.orchestrator import (
    DOCUMENT_FORMAT_TO_TOOL,
    OrchestratorPlanOutput,
    PlanStepSchema,
    orchestrator_agent,
)
from app.agents.registry import AGENT_REGISTRY, get_agent, normalize_agent_id


@pytest.mark.parametrize(
    ("command", "file_format"),
    [
        ("Research autonomous AI agents and create a professional PDF report", "pdf"),
        ("Research autonomous AI agents and create a DOCX report", "docx"),
        ("Research autonomous AI agents and create a TXT report", "txt"),
        ("Research autonomous AI agents and create an Excel report", "xlsx"),
    ],
)
@pytest.mark.asyncio
async def test_planner_repairs_each_omitted_registered_output(
    monkeypatch,
    command,
    file_format,
):
    from app.agents import orchestrator as orchestrator_module

    requirements = orchestrator_module.detect_execution_requirements(command)
    incomplete = orchestrator_agent._build_required_plan(
        command,
        {"research_required": True, "formats": []},
    )

    async def return_incomplete_plan(*args, **kwargs):
        return incomplete

    monkeypatch.setattr(
        orchestrator_module.llm_service,
        "generate_structured",
        return_incomplete_plan,
    )

    plan = await orchestrator_agent.create_plan(command)

    requested_tool = DOCUMENT_FORMAT_TO_TOOL[file_format]
    assert requested_tool in plan.selected_tools
    assert tool_agent_is_allowed(AGENT_REGISTRY, requested_tool)
    assert [step.agent_name for step in plan.steps][0] == "research"
    assert [step.agent_name for step in plan.steps][-1] == "verification"
    document_step = next(step for step in plan.steps if step.tool_id == requested_tool)
    research_step = next(step for step in plan.steps if step.agent_name == "research")
    assert document_step.agent_name == "document"
    assert research_step.step_number in document_step.dependencies
    assert set(requirements["required_tools"]).issubset(plan.selected_tools)


def tool_agent_is_allowed(agent_registry, tool_id):
    return tool_id in agent_registry["document"].allowed_tools


@pytest.mark.asyncio
async def test_research_only_plan_does_not_add_document_tools(monkeypatch):
    from app.agents import orchestrator as orchestrator_module

    command = "Research autonomous AI agents in detail."
    incomplete = OrchestratorPlanOutput(
        intent="Research",
        objective="Research the requested topic.",
        selected_agents=[],
        selected_tools=[],
        steps=[],
    )

    async def return_empty_plan(*args, **kwargs):
        return incomplete

    monkeypatch.setattr(
        orchestrator_module.llm_service,
        "generate_structured",
        return_empty_plan,
    )

    plan = await orchestrator_agent.create_plan(command)

    assert [step.agent_name for step in plan.steps] == [
        "research",
        "verification",
    ]
    assert plan.selected_tools == ["web_search"]


@pytest.mark.asyncio
async def test_llm_failure_recovers_from_requirements_and_preserves_warning(monkeypatch):
    from app.agents import orchestrator as orchestrator_module

    async def fail_planning(*args, **kwargs):
        raise RuntimeError("original Groq planning failure")

    monkeypatch.setattr(
        orchestrator_module.llm_service,
        "generate_structured",
        fail_planning,
    )

    plan = await orchestrator_agent.create_plan(
        "Create a professional PDF report about autonomous AI agents."
    )

    assert "create_pdf" in plan.selected_tools
    assert any("original Groq planning failure" in warning for warning in plan.planning_warnings)


@pytest.mark.asyncio
async def test_planner_rejects_unregistered_tools(monkeypatch):
    from app.agents import orchestrator as orchestrator_module
    from app.agents.orchestrator import PlanStepSchema

    plan_with_unknown_tool = OrchestratorPlanOutput(
        intent="unsupported",
        objective="Unsupported tool should be rejected.",
        selected_agents=["DocumentAgent"],
        selected_tools=["invented_pdf_tool"],
        steps=[
            PlanStepSchema(
                step_number=1,
                agent_name="DocumentAgent",
                action="Call unknown tool",
                tool_id="invented_pdf_tool",
            )
        ],
    )

    async def return_invalid_plan(*args, **kwargs):
        return plan_with_unknown_tool

    monkeypatch.setattr(
        orchestrator_module.llm_service,
        "generate_structured",
        return_invalid_plan,
    )

    with pytest.raises(ValueError, match="unregistered tool"):
        await orchestrator_agent.create_plan("Do an unrelated operation.")


@pytest.mark.parametrize(
    ("alias", "canonical_id"),
    [
        ("ResearchAgent", "research"),
        ("DocumentAgent", "document"),
        ("VerificationAgent", "verification"),
        ("FileManagerAgent", "file_manager"),
        ("CommunicationAgent", "communication"),
        ("BrowserAgent", "browser"),
        ("ShoppingBookingAgent", "shopping_booking"),
    ],
)
def test_agent_aliases_resolve_to_registered_canonical_ids(alias, canonical_id):
    assert normalize_agent_id(alias) == canonical_id
    assert get_agent(alias) is AGENT_REGISTRY[canonical_id]


def test_unknown_agent_alias_is_rejected():
    with pytest.raises(ValueError, match="Unknown agent identifier"):
        normalize_agent_id("ResearchAssistant")


@pytest.mark.asyncio
async def test_pdf_docx_plan_normalizes_names_and_orders_execution(monkeypatch):
    from app.agents import orchestrator as orchestrator_module

    incomplete_plan = OrchestratorPlanOutput(
        intent="Research and document",
        objective="Create both requested report formats.",
        selected_agents=["ResearchAgent", "DocumentAgent", "VerificationAgent"],
        selected_tools=["web_search", "create_docx"],
        steps=[
            PlanStepSchema(
                step_number=1,
                agent_name="ResearchAgent",
                action="Collect research",
                tool_id="web_search",
            ),
            PlanStepSchema(
                step_number=2,
                agent_name="DocumentAgent",
                action="Create DOCX",
                tool_id="create_docx",
                dependencies=[1],
            ),
            PlanStepSchema(
                step_number=3,
                agent_name="VerificationAgent",
                action="Verify output",
                dependencies=[1, 2],
            ),
        ],
    )

    async def return_incomplete_plan(*args, **kwargs):
        return incomplete_plan

    monkeypatch.setattr(
        orchestrator_module.llm_service,
        "generate_structured",
        return_incomplete_plan,
    )

    plan = await orchestrator_agent.create_plan(
        "Research autonomous AI agents and create a professional DOCX and PDF report "
        "and save both files in my workspace."
    )

    assert [step.agent_name for step in plan.steps] == [
        "research",
        "document",
        "document",
        "verification",
    ]
    assert [step.tool_id for step in plan.steps] == [
        "web_search",
        "create_docx",
        "create_pdf",
        None,
    ]
    research_number = plan.steps[0].step_number
    document_numbers = [step.step_number for step in plan.steps[1:3]]
    verification_step = plan.steps[-1]
    assert all(research_number in plan.steps[number - 1].dependencies for number in document_numbers)
    assert set(document_numbers).issubset(verification_step.dependencies)


def test_plan_repair_removes_document_dependency_on_later_verification_step():
    command = "Research autonomous agents and create a DOCX and PDF."
    plan = OrchestratorPlanOutput(
        intent="Research and document",
        objective="Create both formats.",
        selected_agents=["research", "document", "verification"],
        selected_tools=["web_search", "create_docx", "create_pdf"],
        steps=[
            PlanStepSchema(
                step_number=1,
                agent_name="research",
                action="Collect sources",
                tool_id="web_search",
            ),
            PlanStepSchema(
                step_number=2,
                agent_name="verification",
                action="Verify requested outputs",
                dependencies=[1, 3, 4],
            ),
            PlanStepSchema(
                step_number=3,
                agent_name="document",
                action="Create DOCX",
                tool_id="create_docx",
                dependencies=[1],
            ),
            PlanStepSchema(
                step_number=4,
                agent_name="document",
                action="Create PDF",
                tool_id="create_pdf",
                dependencies=[1, 2],
            ),
        ],
    )

    repaired = orchestrator_agent._validate_and_repair_plan(command, plan)

    assert [step.agent_name for step in repaired.steps] == [
        "research",
        "document",
        "document",
        "verification",
    ]
    assert repaired.steps[1].dependencies == [1]
    assert repaired.steps[2].dependencies == [1]
    assert repaired.steps[3].dependencies == [1, 2, 3]
