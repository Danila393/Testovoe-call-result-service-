from __future__ import annotations

from pydantic import BaseModel

from app.enums import HealthStatus


class ComponentHealth(BaseModel):
    ok: bool
    state: str


class HealthResponse(BaseModel):
    status: HealthStatus
    mongodb: ComponentHealth
    consumer: ComponentHealth
