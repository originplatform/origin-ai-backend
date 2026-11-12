"""Structured Logging Module with Sensitive Data Redaction."""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict


# Patterns to redact from logs and prompts
SENSITIVE_PATTERNS = [
    (re.compile(r"gsk_[a-zA-Z0-9]{20,}", re.IGNORECASE), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(password|secret|api_key|token)[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", re.IGNORECASE), r'\1: "[REDACTED]"'),
]


def redact_sensitive_text(text: str) -> str:
    """Mask sensitive patterns in strings to prevent credential leakage."""
    if not isinstance(text, str):
        return text
    redacted = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "task_id"):
            log_data["task_id"] = record.task_id
        if hasattr(record, "agent_name"):
            log_data["agent_name"] = record.agent_name

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(debug: bool = False) -> None:
    """Configure system-wide structured logging."""
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Clear existing handlers
    root_logger.handlers = [handler]

    # Silence noisy external libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance configured for the application."""
    return logging.getLogger(name)

