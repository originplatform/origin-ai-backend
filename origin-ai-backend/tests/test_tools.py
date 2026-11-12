"""Unit tests for universal tool execution system and file/document tools."""

import asyncio
from pathlib import Path
from app.tools.registry import tool_registry


def test_tool_registry_allowlist():
    tools = tool_registry.list_tools()
    tool_ids = [t["tool_id"] for t in tools]
    assert "create_pdf" in tool_ids
    assert "create_docx" in tool_ids
    assert "create_txt" in tool_ids
    assert "create_excel" in tool_ids
    assert "search_workspace_files" in tool_ids

    # Unregistered tool rejection
    result = asyncio.run(tool_registry.execute("arbitrary_hacker_tool", {}))
    assert result.success is False
    assert "not in the approved tool registry" in result.error


def test_create_txt_and_read():
    txt_res = asyncio.run(tool_registry.execute(
        "create_txt",
        {"filename": "test_note.txt", "content": "Autonomous execution verified."}
    ))
    assert txt_res.success is True
    assert txt_res.data["filename"] == "test_note.txt"
    assert Path(txt_res.data["file_path"]).exists()

    read_res = asyncio.run(tool_registry.execute(
        "read_document",
        {"filename_or_path": "test_note.txt"}
    ))
    assert read_res.success is True
    assert "Autonomous execution verified." in read_res.data["content"]


def test_create_docx():
    docx_res = asyncio.run(tool_registry.execute(
        "create_docx",
        {
            "title": "Autonomous Systems Architecture",
            "subtitle": "Phase 1 Execution Report",
            "filename": "auto_arch.docx",
            "sections": [
                {"heading": "Introduction", "content": "Autonomous agents require structured execution."}
            ]
        }
    ))
    assert docx_res.success is True
    target_p = Path(docx_res.data["file_path"])
    assert target_p.exists()
    assert target_p.stat().st_size > 0

    read_res = asyncio.run(tool_registry.execute("read_document", {"filename_or_path": "auto_arch.docx"}))
    assert read_res.success is True
    assert "Autonomous agents require structured execution." in read_res.data["content"]


def test_create_pdf():
    pdf_res = asyncio.run(tool_registry.execute(
        "create_pdf",
        {
            "title": "Verification Report",
            "author": "ORIGIN AI",
            "filename": "verify_report.pdf",
            "sections": [
                {"heading": "Executive Summary", "content": "Verification completed with zero errors."}
            ]
        }
    ))
    assert pdf_res.success is True
    target_p = Path(pdf_res.data["file_path"])
    assert target_p.exists()
    assert target_p.stat().st_size > 0


def test_create_excel():
    excel_res = asyncio.run(tool_registry.execute(
        "create_excel",
        {
            "filename": "metrics.xlsx",
            "headers": ["Metric", "Value", "Status"],
            "rows": [
                ["Tool Count", 15, "Active"],
                ["Test Coverage", "High", "Pass"]
            ]
        }
    ))
    assert excel_res.success is True
    assert Path(excel_res.data["file_path"]).exists()


def test_search_and_prepare_download():
    search_res = asyncio.run(tool_registry.execute("search_workspace_files", {"query": "verify_report"}))
    assert search_res.success is True
    assert len(search_res.data["files"]) >= 1

    prep_res = asyncio.run(tool_registry.execute("prepare_download", {"filename": "verify_report.pdf"}))
    assert prep_res.success is True
    assert "download_url" in prep_res.data
