import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.abspath("."))
from app.tools.registry import tool_registry

async def main():
    print("Listing tools...", flush=True)
    tools = tool_registry.list_tools()
    print(f"Total tools: {len(tools)}", flush=True)

    print("Testing execute arbitrary tool...", flush=True)
    res = await tool_registry.execute("arbitrary_hacker_tool", {})
    print(f"Arbitrary tool: {res.success}, {res.error}", flush=True)

    print("Testing create_txt...", flush=True)
    res_txt = await tool_registry.execute("create_txt", {"filename": "test.txt", "content": "Hello"})
    print(f"Create TXT: {res_txt.success}", flush=True)

    print("Testing search_workspace_files...", flush=True)
    res_search = await tool_registry.execute("search_workspace_files", {"query": "test"})
    print(f"Search files: {res_search.success}, found: {res_search.data['count']}", flush=True)

    print("SUCCESSFUL COMPLETION!", flush=True)

asyncio.run(main())
