"""Pytest configuration and test fixtures."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure test settings
os.environ["ENVIRONMENT"] = "testing"
os.environ["DEBUG"] = "true"

from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, get_db
from app.main import app
from app.tools import tool_registry, init_tools


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Configures isolated test workspace and sqlite in-memory / temporary test database."""
    temp_workspace = Path(tempfile.mkdtemp(prefix="origin_test_workspace_"))
    settings.WORKSPACE_DIR = temp_workspace

    test_db_file = temp_workspace / "test_origin.db"
    test_db_url = f"sqlite:///{test_db_file}"
    settings.DATABASE_URL = test_db_url

    original_engine = SessionLocal.kw["bind"]
    test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    SessionLocal.configure(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    init_tools()

    yield

    # Teardown
    SessionLocal.configure(bind=original_engine)
    test_engine.dispose()
    shutil.rmtree(temp_workspace, ignore_errors=True)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def offline_agent_providers(monkeypatch):
    """Isolate task-flow tests from external LLM and web-search services."""
    from app.agents.orchestrator import (
        OrchestratorPlanOutput,
        PlanStepSchema,
        orchestrator_agent,
    )
    from app.agents.research import REPORT_HEADINGS, llm_service
    from app.tools import research_tools

    queries = [
        "autonomous agents architecture test fixture",
        "agent planning reasoning test fixture",
        "agent memory tool calling test fixture",
        "multi-agent systems test fixture",
        "agent frameworks test fixture",
        "agent applications test fixture",
        "agent security test fixture",
        "future of autonomous agents test fixture",
    ]
    sources = [
        {
            "title": f"TEST-ONLY synthetic source {index}",
            "url": f"https://example.test/research/{index}",
            "snippet": "Synthetic test data for verifying report construction only.",
            "content": "Synthetic test data for verifying report construction only.",
            "source": "example.test",
        }
        for index in range(1, 4)
    ]

    async def fake_generate_structured(prompt, response_model, system_prompt=None):
        if response_model.__name__ == "OrchestratorPlanOutput":
            command = prompt.split("User Command:", 1)[1].splitlines()[0].strip()
            if "email" in command.casefold():
                return OrchestratorPlanOutput(
                    intent="Workspace file discovery and email draft preparation",
                    objective="Locate the requested report and prepare an email draft.",
                    selected_agents=[
                        "file_manager",
                        "communication",
                        "verification",
                    ],
                    selected_tools=["search_workspace_files", "draft_email"],
                    steps=[
                        PlanStepSchema(
                            step_number=1,
                            agent_name="file_manager",
                            action="Locate the project report in the workspace",
                            tool_id="search_workspace_files",
                            input_params={"query": "project_report"},
                        ),
                        PlanStepSchema(
                            step_number=2,
                            agent_name="communication",
                            action="Prepare email draft with report attached",
                            tool_id="draft_email",
                            input_params={
                                "to_email": "recipient@example.com",
                                "subject": "Project Report",
                                "body": "Please find the requested report attached.",
                                "attachments": [],
                            },
                            dependencies=[1],
                        ),
                        PlanStepSchema(
                            step_number=3,
                            agent_name="verification",
                            action="Verify draft and attachment",
                            dependencies=[1, 2],
                        ),
                    ],
                )
            return response_model.model_validate(
                orchestrator_agent._generate_deterministic_plan(command).model_dump()
            )
        if response_model.__name__ == "DocumentDraft":
            from app.agents.document import GeneratedSection

            fixture_text = (
                "TEST-ONLY synthetic explanatory content verifies document creation and extraction. "
                "It is not a factual research source, does not claim web browsing, and must never be "
                "used as a production fallback. The placeholder checks title, section formatting, "
                "readable text, and verification behavior only. "
            ) * 6
            return response_model(
                title="TEST-ONLY Document Fixture",
                subtitle="Synthetic content for workflow tests",
                sections=[
                    GeneratedSection(heading=f"Fixture section {index}", content=fixture_text)
                    for index in range(1, 7)
                ],
            )
        if response_model.__name__ == "ResearchQueryPlan":
            return response_model(queries=queries)
        if response_model.__name__ == "ResearchSynthesis":
            fixture_text = (
                "TEST-ONLY synthetic content exercises report generation and document verification. "
                "It is not research, does not make factual claims, and must never be used by production "
                "providers as a substitute for collected web evidence. The placeholder checks section "
                "formatting, sufficient text extraction, and traceable citation markers only. "
                "[1] [2] [3]. "
            ) * 5
            return response_model(
                summary=fixture_text,
                key_findings=[
                    f"TEST-ONLY fixture finding {index} checks citation propagation and report assembly [1] [2] [3]."
                    for index in range(1, 7)
                ],
                sections=[
                    {"heading": heading, "content": fixture_text}
                    for heading in REPORT_HEADINGS
                ],
            )
        raise AssertionError(f"Unexpected structured response model: {response_model.__name__}")

    async def fake_search(query, max_results=5):
        return sources[:max_results]

    monkeypatch.setattr(llm_service, "generate_structured", fake_generate_structured)
    monkeypatch.setattr(research_tools.search_engine, "search", fake_search)
