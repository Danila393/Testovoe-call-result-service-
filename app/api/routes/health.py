from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import HealthReaderDep
from app.dto import HealthResponse

router = APIRouter(tags=["service"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is not ready"}},
    summary="Готовность сервиса",
)
async def health(reader: HealthReaderDep) -> HealthResponse:
    return await reader.read()
