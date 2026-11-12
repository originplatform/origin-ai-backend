"""Safe Workspace File Management Tools."""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.core.logging import get_logger
from app.core.security import PathSecurity, SecurityError, sanitize_filename
from app.tools.base import BaseTool, RiskLevel, ToolResult

logger = get_logger("origin.tools.file")


# --- 5. Search Workspace Files Tool ---

class SearchFilesInput(BaseModel):
    query: Optional[str] = Field(default="", description="Search query string matching filename")
    extension: Optional[str] = Field(default=None, description="Filter by extension (e.g. .pdf, .docx, .txt)")


class SearchWorkspaceFilesTool(BaseTool):
    tool_id = "search_workspace_files"
    name = "Search Workspace Files"
    description = "Searches for files matching a query or extension within the authorized user workspace."
    input_schema = SearchFilesInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 15

    async def run(self, input_params: SearchFilesInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            workspace_root = PathSecurity.get_workspace_root()
            matches = []

            for root, _, files in os.walk(workspace_root):
                for f in files:
                    if f.startswith(".") or f == ".gitkeep":
                        continue
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(workspace_root)

                    # Extension filter
                    if input_params.extension:
                        req_ext = input_params.extension.lower()
                        if not req_ext.startswith("."):
                            req_ext = "." + req_ext
                        if full_p.suffix.lower() != req_ext:
                            continue

                    # Query filter
                    if input_params.query and input_params.query.lower() not in f.lower():
                        continue

                    stat = full_p.stat()
                    matches.append({
                        "filename": f,
                        "relative_path": str(rel_p).replace("\\", "/"),
                        "size_bytes": stat.st_size,
                        "extension": full_p.suffix.lower(),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    })

            return ToolResult(
                success=True,
                data={"files": matches, "count": len(matches)},
                metadata={"total_found": len(matches)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"File search failed: {str(exc)}")


# --- 6. Read Document Tool ---

class ReadDocumentInput(BaseModel):
    filename_or_path: str = Field(description="Filename or relative path inside workspace")
    max_characters: int = Field(default=20000, description="Maximum characters to read")


class ReadDocumentTool(BaseTool):
    tool_id = "read_document"
    name = "Read Supported Document"
    description = "Reads content from supported documents (TXT, MD, CSV, JSON, DOCX) inside the authorized workspace."
    input_schema = ReadDocumentInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 20

    async def run(self, input_params: ReadDocumentInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            safe_path = PathSecurity.resolve_safe_path(input_params.filename_or_path, allow_create_parent=False)
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"File '{input_params.filename_or_path}' does not exist.")

            PathSecurity.validate_file_size(safe_path)
            suffix = safe_path.suffix.lower()

            content = ""
            metadata: Dict[str, Any] = {"format": suffix}

            if suffix in (".txt", ".md", ".json", ".csv"):
                with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(input_params.max_characters)
            elif suffix == ".docx":
                import docx

                doc = docx.Document(str(safe_path))
                lines = [p.text for p in doc.paragraphs if p.text]
                content = "\n".join(lines)[: input_params.max_characters]
                metadata["paragraphs_count"] = len(doc.paragraphs)
            elif suffix == ".pdf":
                # Basic PDF metadata and text indicator
                content = f"[PDF Document: {safe_path.name}, Size: {safe_path.stat().st_size} bytes]"
            else:
                return ToolResult(success=False, error=f"Unsupported format '{suffix}' for text extraction.")

            return ToolResult(
                success=True,
                data={
                    "filename": safe_path.name,
                    "content": content,
                    "truncated": len(content) >= input_params.max_characters,
                },
                metadata=metadata,
            )
        except SecurityError as sec_err:
            return ToolResult(success=False, error=f"Security violation: {str(sec_err)}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to read file: {str(exc)}")


# --- 7. Copy and Move File Tool ---

class CopyMoveFileInput(BaseModel):
    source_path: str = Field(description="Source filename or path inside workspace")
    destination_path: str = Field(description="Destination filename or path inside workspace")
    action: str = Field(default="copy", description="'copy' or 'move'")


class CopyMoveFileTool(BaseTool):
    tool_id = "copy_move_file"
    name = "Copy or Move File"
    description = "Safely copies or moves files strictly within the authorized workspace."
    input_schema = CopyMoveFileInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 15

    async def run(self, input_params: CopyMoveFileInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            action = input_params.action.lower()
            if action not in ("copy", "move"):
                return ToolResult(success=False, error="Action must be either 'copy' or 'move'.")

            src_path = PathSecurity.resolve_safe_path(input_params.source_path, allow_create_parent=False)
            dst_path = PathSecurity.resolve_safe_path(input_params.destination_path, allow_create_parent=True)

            if not src_path.is_file():
                return ToolResult(success=False, error=f"Source file '{input_params.source_path}' does not exist.")

            if action == "copy":
                shutil.copy2(src_path, dst_path)
            else:
                shutil.move(str(src_path), str(dst_path))

            return ToolResult(
                success=True,
                data={
                    "action": action,
                    "source": str(src_path.name),
                    "destination": str(dst_path.name),
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"File operation failed: {str(exc)}")


# --- 8. Prepare Download Tool ---

class PrepareDownloadInput(BaseModel):
    filename: str = Field(description="Filename located in workspace to prepare for download")


class PrepareDownloadTool(BaseTool):
    tool_id = "prepare_download"
    name = "Prepare File for Download"
    description = "Validates file in workspace and prepares an authorized download reference."
    input_schema = PrepareDownloadInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 10

    async def run(self, input_params: PrepareDownloadInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            safe_path = PathSecurity.resolve_safe_path(input_params.filename, allow_create_parent=False)
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"File '{input_params.filename}' not found in workspace.")

            file_size = PathSecurity.validate_file_size(safe_path)
            file_hash = PathSecurity.compute_sha256(safe_path)

            file_id = None
            if context and "db" in context:
                from app.db.models.file import GeneratedFile

                db = context["db"]
                # Check if already registered
                existing = db.query(GeneratedFile).filter(GeneratedFile.filename == safe_path.name).first()
                if existing:
                    file_id = existing.id
                else:
                    ext = safe_path.suffix.lower().lstrip(".")
                    mime_types = {
                        "pdf": "application/pdf",
                        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "txt": "text/plain",
                        "json": "application/json",
                        "csv": "text/csv",
                    }
                    new_file = GeneratedFile(
                        task_id=context.get("task_id"),
                        filename=safe_path.name,
                        file_path=str(safe_path.relative_to(PathSecurity.get_workspace_root())),
                        file_type=ext,
                        file_size_bytes=file_size,
                        mime_type=mime_types.get(ext, "application/octet-stream"),
                        file_hash=file_hash,
                    )
                    db.add(new_file)
                    db.commit()
                    db.refresh(new_file)
                    file_id = new_file.id

            download_url = f"/api/v1/files/{file_id}/download" if file_id else f"/api/v1/files/raw/{safe_path.name}"

            return ToolResult(
                success=True,
                data={
                    "file_id": file_id,
                    "filename": safe_path.name,
                    "file_size_bytes": file_size,
                    "sha256": file_hash,
                    "download_url": download_url,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to prepare download: {str(exc)}")

