"""Security enforcement, path sanitization, traversal defenses, and safety validation."""

import hashlib
import re
from pathlib import Path
from typing import Optional, Tuple
from app.core.config import settings


class SecurityError(Exception):
    """Raised when a security boundary or validation policy is violated."""
    pass


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes a filename to prevent path injection and invalid characters.
    Disallows directory separators, null bytes, and parent path tokens.
    """
    if not filename or not isinstance(filename, str):
        raise SecurityError("Filename must be a non-empty string")

    # Strip null bytes and control chars
    clean_name = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", filename.strip())

    # Disallow absolute/relative navigation segments
    clean_name = clean_name.replace("/", "_").replace("\\", "_")
    clean_name = re.sub(r"\.\.+", "_", clean_name)

    # Allow alphanumeric, hyphens, underscores, dots, spaces
    clean_name = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", clean_name).strip()
    # Strip leading/trailing underscores and dots to avoid hidden files or relative paths
    clean_name = re.sub(r"^[_ \.]+|[_ \.]+$", "", clean_name)

    if not clean_name or clean_name in (".", "..", "_"):
        clean_name = f"document_{hashlib.md5(filename.encode()).hexdigest()[:8]}"

    return clean_name


class PathSecurity:
    """Guarantees strict isolation within the user workspace directory."""

    @staticmethod
    def get_workspace_root() -> Path:
        """Return the fully resolved canonical workspace root path."""
        root = settings.WORKSPACE_DIR.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def resolve_safe_path(cls, relative_or_absolute_path: str, allow_create_parent: bool = True) -> Path:
        """
        Resolves a path and ensures it stays strictly inside the workspace boundary.
        Prevents path traversal, directory breakouts, and symlink attacks.
        """
        workspace_root = cls.get_workspace_root()

        # Strip any leading slashes or drive letters to treat as workspace-relative if given as relative
        raw_path = Path(relative_or_absolute_path)
        if raw_path.is_absolute():
            try:
                candidate = raw_path.resolve()
            except Exception as exc:
                raise SecurityError(f"Invalid path representation: {exc}")
        else:
            candidate = (workspace_root / raw_path).resolve()

        # Strict containment check
        try:
            candidate.relative_to(workspace_root)
        except ValueError:
            raise SecurityError(
                f"Path traversal detected! Path '{candidate}' is outside authorized workspace '{workspace_root}'"
            )

        # Enforce allowed extensions if an extension exists
        suffix = candidate.suffix.lower()
        if suffix and suffix not in settings.ALLOWED_FILE_EXTENSIONS:
            raise SecurityError(
                f"Disallowed file extension '{suffix}'. Allowed: {', '.join(settings.ALLOWED_FILE_EXTENSIONS)}"
            )

        if allow_create_parent:
            candidate.parent.mkdir(parents=True, exist_ok=True)

        return candidate

    @classmethod
    def validate_file_size(cls, file_path: Path) -> int:
        """Verifies that the file size does not exceed the allowed maximum."""
        if not file_path.is_file():
            raise SecurityError(f"Target path '{file_path}' is not an existing file.")

        size_bytes = file_path.stat().st_size
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if size_bytes > max_bytes:
            raise SecurityError(
                f"File size ({size_bytes / 1024 / 1024:.2f} MB) exceeds maximum allowed limit ({settings.MAX_FILE_SIZE_MB} MB)"
            )
        return size_bytes

    @classmethod
    def compute_sha256(cls, file_path: Path) -> str:
        """Computes SHA-256 hash of a file for integrity verification."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


class PromptDefense:
    """Defenses against prompt injection and malicious control sequences."""

    SUSPICIOUS_PHRASES = [
        "ignore previous instructions",
        "disregard all prior instructions",
        "system prompt override",
        "drop database",
        "rm -rf",
        "delete from users",
        "cat /etc/passwd",
        "eval(",
        "__import__",
    ]

    @classmethod
    def inspect_prompt(cls, user_command: str) -> Tuple[bool, Optional[str]]:
        """Scans input for common jailbreak and injection patterns."""
        lower_cmd = user_command.lower()
        for phrase in cls.SUSPICIOUS_PHRASES:
            if phrase in lower_cmd:
                return False, f"Potentially malicious instruction detected: '{phrase}'"
        return True, None
