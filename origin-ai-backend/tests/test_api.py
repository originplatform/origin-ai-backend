"""API endpoint integration tests."""

import pytest


def test_root_and_health(client):
    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "ORIGIN AI" in root_res.json()["name"]

    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["database_connected"] is True
    assert health_res.json()["workspace_accessible"] is True


def test_list_agents(client):
    agents_res = client.get("/api/v1/agents")
    assert agents_res.status_code == 200
    agent_names = [a["name"] for a in agents_res.json()]
    assert "Orchestrator Agent" in agent_names
    assert "Document Agent" in agent_names
    assert "Verification Agent" in agent_names
    assert "Communication Agent" in agent_names


def test_task_submission_and_lifecycle(client):
    # Submit a report task
    cmd = "Create a professional DOCX and PDF report about autonomous AI agents and save both files in my workspace."
    post_res = client.post("/api/v1/tasks", json={"command": cmd})
    assert post_res.status_code == 201
    task_data = post_res.json()
    task_id = task_data["id"]
    assert task_data["status"] in ("COMPLETED", "RUNNING")
    assert task_data["intent"] is not None

    # Retrieve task
    get_res = client.get(f"/api/v1/tasks/{task_id}")
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["id"] == task_id
    assert len(retrieved["steps"]) >= 3

    # Check files endpoint
    files_res = client.get("/api/v1/files")
    assert files_res.status_code == 200
    files_list = files_res.json()
    assert len(files_list) >= 1

    # Test file download
    first_file = files_list[0]
    dl_res = client.get(f"/api/v1/files/{first_file['id']}/download")
    assert dl_res.status_code == 200
    assert len(dl_res.content) > 0


def test_task_cancellation(client):
    # Submit with background flag so it can be cancelled
    post_res = client.post(
        "/api/v1/tasks?run_in_background=true",
        json={"command": "Research quantum computing developments"}
    )
    assert post_res.status_code == 201
    task_id = post_res.json()["id"]

    cancel_res = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

