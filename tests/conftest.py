"""Shared fixtures.

Integration fixtures connect to real MongoDB / RabbitMQ at ``MONGODB_URL`` / ``RABBITMQ_URL``
(defaults: localhost). If a service is unreachable the dependent tests are skipped with the reason.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import aio_pika
import pytest
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.infrastructure.mongo import create_client, ensure_indexes, ping
from app.repositories.mongo import Document


@pytest.fixture
def settings() -> Settings:
    suffix = uuid.uuid4().hex[:8]
    return Settings(
        mongodb_url=os.environ.get("MONGODB_URL", "mongodb://localhost:27017"),
        mongodb_db=f"test_calls_{suffix}",
        mongodb_timeout_ms=1500,
        rabbitmq_url=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        retry_delay_seconds=0.05,
        reconnect_initial_delay_seconds=0.1,
        reconnect_max_delay_seconds=0.5,
    )


@pytest.fixture
async def mongo_db(settings: Settings) -> AsyncIterator[AsyncDatabase[Document]]:
    client = create_client(settings)
    if not await ping(client):
        await client.close()
        pytest.skip(f"MongoDB is not reachable at {settings.mongodb_url}")
    db = client[settings.mongodb_db]
    await ensure_indexes(db)
    try:
        yield db
    finally:
        await client.drop_database(settings.mongodb_db)
        await client.close()


@pytest.fixture
async def rabbitmq(settings: Settings) -> AsyncIterator[aio_pika.abc.AbstractConnection]:
    try:
        connection = await aio_pika.connect(settings.rabbitmq_url, timeout=3)
    except (OSError, aio_pika.exceptions.AMQPError) as exc:
        pytest.skip(f"RabbitMQ is not reachable at {settings.rabbitmq_url}: {exc}")
    try:
        yield connection
    finally:
        await connection.close()
