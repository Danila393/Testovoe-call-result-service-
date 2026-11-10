"""Composition root: builds and owns every long-lived object of the process."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial

from pymongo import AsyncMongoClient

from app.config import Settings
from app.consumers import CallConsumer
from app.enums import ConsumerState
from app.infrastructure.mongo import create_client, ensure_indexes, ping
from app.repositories import MongoCallStore, MongoCampaignStore
from app.repositories.mongo import Document
from app.services.commands import IngestCallHandler
from app.services.readers import CampaignCallsReader, HealthReader

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Container:
    settings: Settings
    mongo_client: AsyncMongoClient[Document]
    ingest_call: IngestCallHandler
    campaign_calls_reader: CampaignCallsReader
    health_reader: HealthReader
    consumer: CallConsumer | None

    @classmethod
    async def create(cls, settings: Settings, *, run_consumer: bool = True) -> Container:
        """Connect, ensure indexes and (optionally) start the consumer.

        Fails fast if MongoDB is unreachable: the container restart policy retries startup.
        """
        client = create_client(settings)
        db = client[settings.mongodb_db]
        await ensure_indexes(db)
        campaigns, calls = MongoCampaignStore(db), MongoCallStore(db)
        ingest_call = IngestCallHandler(campaigns, calls)
        consumer = CallConsumer(settings, ingest_call) if run_consumer else None

        def consumer_state() -> ConsumerState:
            return consumer.state if consumer is not None else ConsumerState.STOPPED

        container = cls(
            settings=settings,
            mongo_client=client,
            ingest_call=ingest_call,
            campaign_calls_reader=CampaignCallsReader(campaigns, calls),
            health_reader=HealthReader(partial(ping, client), consumer_state),
            consumer=consumer,
        )
        if consumer is not None:
            consumer.start()
        logger.info("application started", extra={"database": settings.mongodb_db})
        return container

    async def aclose(self) -> None:
        if self.consumer is not None:
            await self.consumer.stop()
        await self.mongo_client.close()
        logger.info("application stopped")
