"""HTTP layer: thin routes, dependencies and the mapping of application errors."""

from fastapi import APIRouter

from app.api.routes import campaigns, health

router = APIRouter()
router.include_router(campaigns.router)
router.include_router(health.router)

__all__ = ["router"]
