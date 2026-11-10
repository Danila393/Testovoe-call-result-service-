"""FastAPI application factory. Run with ``uvicorn app.main:build_default_app --factory``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.api.errors import register_exception_handlers
from app.config import Settings
from app.container import Container
from app.log import configure_logging


def create_app(settings: Settings | None = None, *, run_consumer: bool = True) -> FastAPI:
    """Build the app. ``run_consumer=False`` serves only HTTP."""
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await Container.create(resolved, run_consumer=run_consumer)
        app.state.container = container
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title="Call results service",
        version="1.0.0",
        description=(
            "Получает результаты звонков из RabbitMQ, сохраняет в MongoDB и отдаёт по REST."
        ),
        lifespan=lifespan,
    )
    app.include_router(router)
    register_exception_handlers(app)
    return app


def build_default_app() -> FastAPI:
    """Entry point for ``uvicorn app.main:build_default_app --factory``."""
    settings = Settings()
    configure_logging(settings.log_level)
    return create_app(settings)
