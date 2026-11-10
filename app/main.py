"""FastAPI application factory. Run with ``uvicorn app.main:build_default_app --factory``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import Stores, router
from app.config import Settings
from app.consumer import CallConsumer
from app.db import create_client, ensure_indexes
from app.log import configure_logging
from app.repository import MongoCallStore, MongoCampaignStore
from app.service import CallIngestService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, run_consumer: bool = True) -> FastAPI:
    """Build the app. ``run_consumer=False`` serves only HTTP (used in API tests)."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = create_client(settings)
        db = client[settings.mongodb_db]
        # Fail fast if MongoDB is unreachable: the container restart policy retries startup.
        await ensure_indexes(db)
        campaigns, calls = MongoCampaignStore(db), MongoCallStore(db)
        app.state.mongo_client = client
        app.state.stores = Stores(campaigns=campaigns, calls=calls)
        app.state.consumer = None
        if run_consumer:
            consumer = CallConsumer(settings, CallIngestService(campaigns, calls))
            consumer.start()
            app.state.consumer = consumer
        logger.info("application started", extra={"database": settings.mongodb_db})
        try:
            yield
        finally:
            if app.state.consumer is not None:
                await app.state.consumer.stop()
            await client.close()
            logger.info("application stopped")

    app = FastAPI(
        title="Call results service",
        version="1.0.0",
        description=(
            "Получает результаты звонков из RabbitMQ, сохраняет в MongoDB и отдаёт по REST."
        ),
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


def build_default_app() -> FastAPI:
    """Entry point for ``uvicorn app.main:build_default_app --factory``."""
    settings = Settings()
    configure_logging(settings.log_level)
    return create_app(settings)
