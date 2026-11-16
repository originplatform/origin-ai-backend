"""Communication Tools and Adapter Architecture."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.security import PathSecurity
from app.services.gmail_service import GmailServiceError
from app.services.gmail_service import gmail_service
from app.tools.base import BaseTool, RiskLevel, ToolResult

logger = get_logger("origin.tools.communication")


class EmailProviderAdapter(ABC):
    """Interface for external email service providers (e.g. SMTP, SendGrid, Gmail API)."""

    @abstractmethod
    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        pass


class UnconfiguredEmailProvider(EmailProviderAdapter):
    """Default adapter enforcing honest integration boundary."""

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            "Email service integration is not configured. Connect an authorized email provider (e.g. SMTP or Gmail API) to enable real sending."
        )


class GmailEmailProviderAdapter(EmailProviderAdapter):
    """Fail-closed adapter while Gmail sending is outside the current phase."""

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            "Gmail sending is disabled in this phase; only read-only Gmail access is available."
        )


# Active email adapter
email_provider: EmailProviderAdapter = GmailEmailProviderAdapter()


class GmailReadInput(BaseModel):
    operation: Literal["inbox", "unread", "search", "message", "thread"]
    query: Optional[str] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    page_token: Optional[str] = None
    max_results: int = Field(default=10, ge=1, le=100)
    summarize: bool = False


class GmailReadTool(BaseTool):
    """Reads only the authenticated owner's Gmail data."""

    tool_id = "gmail_read"
    name = "Read Gmail"
    description = (
        "Reads inbox messages, unread messages, searches, a message, or a thread "
        "using the authenticated owner's read-only Gmail connection."
    )
    input_schema = GmailReadInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 45

    async def run(
        self,
        input_params: GmailReadInput,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        context = context or {}
        db = context.get("db")
        owner_id = context.get("user_id")
        if db is None or not isinstance(owner_id, str) or not owner_id:
            return ToolResult(
                success=False,
                error="Gmail access requires an authenticated owner context.",
            )
        try:
            if input_params.operation in {"inbox", "unread", "search"}:
                if input_params.operation == "search" and not input_params.query:
                    return ToolResult(success=False, error="A Gmail search query is required.")
                result = await gmail_service.list_messages(
                    db,
                    owner_id,
                    unread_only=input_params.operation == "unread",
                    query=input_params.query if input_params.operation == "search" else None,
                    page_token=input_params.page_token,
                    max_results=input_params.max_results,
                )
            elif input_params.operation == "message":
                if not input_params.message_id:
                    return ToolResult(success=False, error="A Gmail message ID is required.")
                result = await gmail_service.get_message(
                    db,
                    owner_id,
                    input_params.message_id,
                )
            else:
                if not input_params.thread_id:
                    return ToolResult(success=False, error="A Gmail thread ID is required.")
                result = await gmail_service.get_thread(
                    db,
                    owner_id,
                    input_params.thread_id,
                )
            if input_params.summarize:
                result = gmail_service.add_extractive_summary(result)
            return ToolResult(success=True, data=result)
        except GmailServiceError as exc:
            return ToolResult(success=False, error=str(exc))


# --- 1. Draft Email Tool (LOW_RISK) ---

class DraftEmailInput(BaseModel):
    to_email: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Draft email body text")
    attachments: Optional[List[str]] = Field(default=None, description="List of filenames in workspace to attach")


class DraftEmailTool(BaseTool):
    tool_id = "draft_email"
    name = "Draft Email"
    description = "Prepares an email draft with optional workspace attachments. Does not send external messages."
    input_schema = DraftEmailInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 15

    async def run(self, input_params: DraftEmailInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            verified_attachments = []
            if input_params.attachments:
                for att_name in input_params.attachments:
                    safe_p = PathSecurity.resolve_safe_path(att_name, allow_create_parent=False)
                    if safe_p.is_file():
                        verified_attachments.append({
                            "filename": safe_p.name,
                            "path": str(safe_p),
                            "size_bytes": safe_p.stat().st_size,
                        })
                    else:
                        return ToolResult(
                            success=False,
                            error=f"Attachment file '{att_name}' not found in authorized workspace.",
                        )

            draft_payload = {
                "to_email": input_params.to_email,
                "subject": input_params.subject,
                "body": input_params.body,
                "attachments": verified_attachments,
                "status": "DRAFT_READY",
            }

            return ToolResult(
                success=True,
                data=draft_payload,
                metadata={"requires_approval_to_send": True},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to prepare email draft: {str(exc)}")


# --- 2. Send Email Tool (REQUIRES_APPROVAL) ---

class SendEmailInput(BaseModel):
    to_email: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body text")
    attachments: Optional[List[str]] = Field(default=None, description="Verified workspace attachments")


class SendEmailTool(BaseTool):
    tool_id = "send_email"
    name = "Send Email"
    description = "Dispatches an email message via an authorized email integration. Requires explicit user approval."
    input_schema = SendEmailInput
    risk_level = RiskLevel.REQUIRES_APPROVAL
    timeout_seconds = 30
    required_permissions = ["communication.email.send"]

    async def run(self, input_params: SendEmailInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        return ToolResult(
            success=False,
            error="Email sending is disabled in this phase; only read-only Gmail access is available.",
        )

