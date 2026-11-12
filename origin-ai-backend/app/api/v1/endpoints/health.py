"""Health check endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.tools.registry import tool_registry

router = APIRouter()


@router.get("/health", summary="System Health Status")
def health_check(db: Session = Depends(get_db)):
    """Verifies operational status of database, storage workspace, and tool registry."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    workspace_ok = settings.WORKSPACE_DIR.exists() and settings.WORKSPACE_DIR.is_dir()
    registered_tools = len(tool_registry.list_tools())

    return {
        "status": "healthy" if db_ok and workspace_ok else "degraded",
        "database_connected": db_ok,
        "workspace_path": str(settings.WORKSPACE_DIR),
        "workspace_accessible": workspace_ok,
        "registered_tools_count": registered_tools,
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
    }

