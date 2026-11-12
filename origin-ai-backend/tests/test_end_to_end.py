"""End-to-End Acceptance Tests specified in ORIGIN AI Phase 1 Blueprint."""

from pathlib import Path
import pytest
from app.core.security import PathSecurity


@pytest.mark.asyncio
async def test_end_to_end_report_generation(client):
    """
    Acceptance Test 1:
    'Create a professional DOCX and PDF report about autonomous AI agents and save both files in my workspace.'
    """
    command = "Create a professional DOCX and PDF report about autonomous AI agents and save both files in my workspace."

    response = client.post("/api/v1/tasks", json={"command": command})
    assert response.status_code == 201
    data = response.json()

    task_id = data["id"]
    assert data["status"] == "COMPLETED"
    assert "Research and generate" in data["intent"]
    assert "Research Agent" in data["selected_agents"]
    assert "Document Agent" in data["selected_agents"]
    assert "Verification Agent" in data["selected_agents"]

    # Verify execution steps
    steps = data["steps"]
    assert len(steps) >= 4

    # 1. Research step
    research_step = next(s for s in steps if s["agent_name"] == "Research Agent")
    assert research_step["status"] == "COMPLETED"
    assert research_step["output_data"] is not None

    # 2. DOCX & PDF generation steps
    docx_step = next((s for s in steps if s["tool_name"] == "create_docx"), None)
    assert docx_step is not None
    assert docx_step["status"] == "COMPLETED"

    pdf_step = next((s for s in steps if s["tool_name"] == "create_pdf"), None)
    assert pdf_step is not None
    assert pdf_step["status"] == "COMPLETED"

    # 3. Verification step
    verify_step = next(s for s in steps if s["agent_name"] == "Verification Agent")
    assert verify_step["status"] in ("COMPLETED", "PENDING")

    # 4. Verify physical files on disk in workspace
    final_res = data["final_result"]
    assert final_res is not None
    generated_files = final_res["generated_files"]
    assert len(generated_files) >= 2

    for gf in generated_files:
        fname = gf["filename"]
        disk_path = PathSecurity.resolve_safe_path(fname, allow_create_parent=False)
        assert disk_path.is_file(), f"Physical file '{fname}' was not created on disk!"
        assert disk_path.stat().st_size > 0, f"File '{fname}' is empty (0 bytes)!"
        assert gf["download_url"].startswith("/api/v1/files/")

        # Test download response
        dl_res = client.get(gf["download_url"])
        assert dl_res.status_code == 200
        assert len(dl_res.content) == disk_path.stat().st_size


@pytest.mark.asyncio
async def test_end_to_end_find_and_email_draft(client):
    """
    Acceptance Test 2:
    'Find the project report in my workspace and prepare an email draft with it attached.'
    """
    # 1. Pre-condition: Ensure a project report exists in workspace
    from app.tools.registry import tool_registry
    await tool_registry.execute(
        "create_docx",
        {
            "title": "Project Report",
            "filename": "project_report.docx",
            "sections": [{"heading": "Progress", "content": "Phase 1 engine is operational."}],
        }
    )

    command = "Find the project report in my workspace and prepare an email draft with it attached."

    response = client.post("/api/v1/tasks", json={"command": command})
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "COMPLETED"
    assert "File Management Agent" in data["selected_agents"]
    assert "Communication Agent" in data["selected_agents"]

    steps = data["steps"]
    file_step = next(s for s in steps if s["agent_name"] == "File Management Agent")
    assert file_step["status"] == "COMPLETED"
    assert file_step["output_data"]["count"] >= 1

    comm_step = next(s for s in steps if s["agent_name"] == "Communication Agent")
    assert comm_step["status"] == "COMPLETED"
    draft_data = comm_step["output_data"]
    assert draft_data["status"] == "DRAFT_READY"
    assert len(draft_data["attachments"]) >= 1
    assert any("project_report" in att["filename"] for att in draft_data["attachments"])

