"""Tool initialization and automatic registry bootstrapping."""

from app.tools.base import BaseTool, RiskLevel, ToolResult
from app.tools.registry import ToolRegistry, tool_registry
from app.tools.document_tools import (
    CreatePDFTool,
    CreateDOCXTool,
    CreateTXTTool,
    CreateExcelTool,
)
from app.tools.file_tools import (
    SearchWorkspaceFilesTool,
    ReadDocumentTool,
    CopyMoveFileTool,
    PrepareDownloadTool,
)
from app.tools.communication_tools import DraftEmailTool, SendEmailTool
from app.tools.browser_tools import NavigateTool, SubmitFormTool
from app.tools.research_tools import WebSearchTool
from app.tools.shopping_booking_tools import SearchProductsTool, BookMovieTicketsTool


def init_tools() -> None:
    """Populates global tool registry with all approved tools."""
    tools = [
        # Working Document Generation Tools
        CreatePDFTool(),
        CreateDOCXTool(),
        CreateTXTTool(),
        CreateExcelTool(),
        # Working Workspace File Tools
        SearchWorkspaceFilesTool(),
        ReadDocumentTool(),
        CopyMoveFileTool(),
        PrepareDownloadTool(),
        # Communication Tools
        DraftEmailTool(),
        SendEmailTool(),
        # Research Tool
        WebSearchTool(),
        # Browser Automation Tools
        NavigateTool(),
        SubmitFormTool(),
        # Commerce Tools
        SearchProductsTool(),
        BookMovieTicketsTool(),
    ]
    for t in tools:
        tool_registry.register(t)


init_tools()

__all__ = [
    "tool_registry",
    "BaseTool",
    "RiskLevel",
    "ToolResult",
    "CreatePDFTool",
    "CreateDOCXTool",
    "CreateTXTTool",
    "CreateExcelTool",
    "SearchWorkspaceFilesTool",
    "ReadDocumentTool",
    "CopyMoveFileTool",
    "PrepareDownloadTool",
    "DraftEmailTool",
    "SendEmailTool",
    "WebSearchTool",
    "NavigateTool",
    "SubmitFormTool",
    "SearchProductsTool",
    "BookMovieTicketsTool",
]

