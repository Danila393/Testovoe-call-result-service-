from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Хранилище временно недоступно"])
