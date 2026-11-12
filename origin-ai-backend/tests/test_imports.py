import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath("."))
from app.tools import tool_registry

async def run_tests():
    print("Listing tools...", flush=True)
    tools = tool_registry.list_tools()
    print("Found tools:", len(tools), flush=True)

    print("Testing create_txt...", flush=True)
    res_txt = await tool_registry.execute("create_txt", {"filename": "test.txt", "content": "Hello"})
    print("Create TXT result:", res_txt.success, res_txt.data, flush=True)

    print("Testing read_document...", flush=True)
    res_read = await tool_registry.execute("read_document", {"filename_or_path": "test.txt"})
    print("Read result:", res_read.success, res_read.data, flush=True)

    print("Testing create_docx...", flush=True)
    res_docx = await tool_registry.execute("create_docx", {
        "title": "Docx Test",
        "sections": [{"heading": "Sec1", "content": "Paragraph content"}]
    })
    print("Create DOCX result:", res_docx.success, res_docx.data["filename"], flush=True)

    print("Testing create_pdf...", flush=True)
    res_pdf = await tool_registry.execute("create_pdf", {
        "title": "PDF Test",
        "sections": [{"heading": "Sec1", "content": "Paragraph content"}]
    })
    print("Create PDF result:", res_pdf.success, res_pdf.data["filename"], flush=True)

    print("All tool executions passed successfully!", flush=True)

asyncio.run(run_tests())
