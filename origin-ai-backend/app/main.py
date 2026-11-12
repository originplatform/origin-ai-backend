"""ORIGIN AI Backend Entry Point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints.health import health_check
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import Base
from app.db.session import engine
from app.tools import tool_registry

logger = get_logger("origin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    setup_logging(debug=settings.DEBUG)
    logger.info("Initializing ORIGIN AI Backend engine...")

    # Ensure tables exist (Alembic handles migrations, this is safety fallback)
    Base.metadata.create_all(bind=engine)

    # Ensure workspace directory is initialized
    settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Workspace root active at: {settings.WORKSPACE_DIR}")
    logger.info(f"Total tools registered in execution registry: {len(tool_registry.list_tools())}")

    yield
    logger.info("Shutting down ORIGIN AI Backend engine.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Autonomous Personal AI Operator — Core Execution Engine",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
def root_info():
    """Welcome and overview of ORIGIN AI Operator Backend."""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "description": "Autonomous Personal AI Operator Core Execution Engine",
        "documentation": "/docs",
        "health": "/health",
        "api_v1": settings.API_V1_STR,
    }


# Direct /health route as required by specifications
app.add_api_route("/health", health_check, methods=["GET"], tags=["Health"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

