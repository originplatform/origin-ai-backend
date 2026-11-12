"""Browser Automation Adapter Architecture using Playwright interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, HttpUrl
from app.core.logging import get_logger
from app.core.security import SecurityError
from app.tools.base import BaseTool, RiskLevel, ToolResult

logger = get_logger("origin.tools.browser")


# Prohibited host patterns for SSRF prevention
FORBIDDEN_HOSTS = {"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "0.0.0.0"}


def validate_public_url(url_str: str) -> str:
    """Enforces SSRF prevention by disallowing internal loopback and cloud metadata endpoints."""
    parsed = urlparse(url_str)
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        raise SecurityError("Only standard http/https schemes are supported.")

    hostname = (parsed.hostname or "").lower()
    if hostname in FORBIDDEN_HOSTS or hostname.startswith("192.168.") or hostname.startswith("10."):
        raise SecurityError(f"Access to private or metadata endpoint '{hostname}' is blocked.")

    return url_str


class BrowserAdapterInterface(ABC):
    """Abstract interface for browser automation engine."""

    @abstractmethod
    async def navigate_and_extract(self, url: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def fill_and_submit(self, url: str, form_data: Dict[str, Any]) -> Dict[str, Any]:
        pass


class PlaywrightAdapterStub(BrowserAdapterInterface):
    """Stub adapter pending live Playwright headless browser setup."""

    async def navigate_and_extract(self, url: str) -> Dict[str, Any]:
        raise NotImplementedError(
            "Playwright browser automation is configured as an adapter interface. Install browser binaries to enable headless execution."
        )

    async def fill_and_submit(self, url: str, form_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(
            "Browser form automation requires an active Playwright browser session."
        )


browser_adapter: BrowserAdapterInterface = PlaywrightAdapterStub()


class NavigateInput(BaseModel):
    url: str = Field(description="Target public URL to visit")


class NavigateTool(BaseTool):
    tool_id = "browser_navigate"
    name = "Browser Navigate & Extract"
    description = "Navigates to a public website and extracts visible text content."
    input_schema = NavigateInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 45

    async def run(self, input_params: NavigateInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            safe_url = validate_public_url(input_params.url)
            data = await browser_adapter.navigate_and_extract(safe_url)
            return ToolResult(success=True, data=data)
        except NotImplementedError as nie:
            return ToolResult(
                success=False,
                error=str(nie),
                metadata={"adapter": "playwright", "configured": False},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Navigation failed: {str(exc)}")


class FormSubmitInput(BaseModel):
    url: str = Field(description="Target form URL")
    form_data: Dict[str, Any] = Field(description="Key-value pairs to fill into form")


class SubmitFormTool(BaseTool):
    tool_id = "browser_submit_form"
    name = "Browser Submit Form"
    description = "Fills and submits a web form. High risk operation requiring explicit approval."
    input_schema = FormSubmitInput
    risk_level = RiskLevel.REQUIRES_APPROVAL
    timeout_seconds = 45
    required_permissions = ["browser.interact.submit"]

    async def run(self, input_params: FormSubmitInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            safe_url = validate_public_url(input_params.url)
            data = await browser_adapter.fill_and_submit(safe_url, input_params.form_data)
            return ToolResult(success=True, data=data)
        except NotImplementedError as nie:
            return ToolResult(
                success=False,
                error=str(nie),
                metadata={"adapter": "playwright", "configured": False},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Form submission failed: {str(exc)}")

