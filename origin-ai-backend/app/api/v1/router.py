"""API v1 router composition."""

from fastapi import APIRouter
from app.api.v1.endpoints import agents, approvals, files, health, tasks

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(agents.router, tags=["Agents"])
api_router.include_router(tasks.router, tags=["Tasks"])
api_router.include_router(approvals.router, tags=["Approvals"])
api_router.include_router(files.router, tags=["Files"])

