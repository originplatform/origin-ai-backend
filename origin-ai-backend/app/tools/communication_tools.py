"""Communication Tools and Adapter Architecture."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, EmailStr
from app.core.logging import get_logger
from app.core.security import PathSecurity
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
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            "Email service integration is not configured. Connect an authorized email provider (e.g. SMTP or Gmail API) to enable real sending."
        )


# Active email adapter
email_provider: EmailProviderAdapter = UnconfiguredEmailProvider()


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
        try:
            result = await email_provider.send_email(
                to_email=input_params.to_email,
                subject=input_params.subject,
                body=input_params.body,
                attachments=input_params.attachments,
            )
            return ToolResult(success=True, data=result)
        except NotImplementedError as nie:
            return ToolResult(
                success=False,
                error=str(nie),
                metadata={"integration_configured": False},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Email dispatch failed: {str(exc)}")

