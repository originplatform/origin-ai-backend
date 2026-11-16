"""Schemas for owner-scoped communication and contact management."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email_address: EmailStr
    aliases: Optional[List[str]] = Field(default_factory=list)
    organization: Optional[str] = Field(default=None, max_length=255)
    verification_status: str = Field(default="unverified")


class ContactUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email_address: Optional[EmailStr] = None
    aliases: Optional[List[str]] = None
    organization: Optional[str] = Field(default=None, max_length=255)
    verification_status: Optional[str] = Field(default=None, max_length=32)


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    full_name: str
    email_address: str
    aliases: Optional[List[str]] = None
    organization: Optional[str] = None
    verification_status: str
    created_at: datetime
    updated_at: datetime


class GmailConnectionStatusResponse(BaseModel):
    connected: bool
    status: str
    email_address: Optional[str] = None
    provider: str = "gmail"
    scopes: List[str] = Field(default_factory=list)


class DraftEmailRequest(BaseModel):
    to_email: EmailStr
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    attachments: Optional[List[str]] = Field(default_factory=list)


class GmailMessageSummary(BaseModel):
    id: str
    thread_id: str
    sender: str = ""
    recipient: str = ""
    subject: str = ""
    date: str = ""
    snippet: str = ""
    body: str = ""
    labels: List[str] = Field(default_factory=list)


class GmailMessagePage(BaseModel):
    messages: List[GmailMessageSummary] = Field(default_factory=list)
    next_page_token: Optional[str] = None
    result_size_estimate: int = 0
    summary: Optional[str] = None
    summary_message_id: Optional[str] = None


class GmailThreadResponse(BaseModel):
    id: str
    history_id: Optional[str] = None
    messages: List[GmailMessageSummary] = Field(default_factory=list)
