"""Full app (lifespan: MongoDB + consumer) + producer: the reviewer's scenario."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import aio_pika
import httpx
import pytest
from fastapi import FastAPI
from pymongo.asynchronous.database import AsyncDatabase

import producer
from app.config import Settings
from app.infrastructure.rabbitmq import DEAD_LETTER_QUEUE, QUEUE, declare_topology
from app.main import create_app
from app.repositories.mongo import Document

pytestmark = pytest.mark.integration


@pytest.fixture
async def app_client(
    settings: Settings,
    mongo_db: AsyncDatabase[Document],
    rabbitmq: aio_pika.abc.AbstractConnection,
) -> AsyncIterator[httpx.AsyncClient]:
    channel = await rabbitmq.channel()
    await declare_topology(channel)
    for name in (QUEUE, DEAD_LETTER_QUEUE):
        await (await channel.get_queue(name)).purge()

    app: FastAPI = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def wait_healthy(client: httpx.AsyncClient) -> dict[str, object]:
    for _ in range(200):
        resp = await client.get("/health")
        if resp.status_code == 200:
            return dict(resp.json())
        await asyncio.sleep(0.05)
    raise AssertionError(f"service never became healthy: {resp.json()}")


async def wait_for_calls(client: httpx.AsyncClient, campaign_id: str, n: int) -> dict[str, Any]:
    for _ in range(200):
        body = (await client.get(f"/campaigns/{campaign_id}/calls")).json()
        if body.get("total") == n:
            assert len(body["calls"]) == n  # page and total come from one query
            return dict(body)
        await asyncio.sleep(0.05)
    raise AssertionError(f"expected {n} calls for {campaign_id}, last response: {body}")


async def test_reviewer_scenario(app_client: httpx.AsyncClient, settings: Settings) -> None:
    health = await wait_healthy(app_client)
    assert health == {
        "status": "ok",
        "mongodb": {"ok": True, "state": "up"},
        "consumer": {"ok": True, "state": "consuming"},
    }

    before = await app_client.get("/campaigns/camp_001/calls")
    assert before.json() == {"detail": "Кампания не найдена"}

    await producer.publish(settings.rabbitmq_url, producer.MESSAGES)

    camp_001 = await wait_for_calls(app_client, "camp_001", 2)
    assert [c["call_id"] for c in camp_001["calls"]] == ["call_0001", "call_0002"]
    camp_002 = await wait_for_calls(app_client, "camp_002", 2)
    assert [c["call_id"] for c in camp_002["calls"]] == ["call_0003", "call_0004"]

    # Running the producer again must not change the answer.
    await producer.publish(settings.rabbitmq_url, producer.MESSAGES)
    await asyncio.sleep(0.5)
    again = (await app_client.get("/campaigns/camp_001/calls")).json()
    assert again["total"] == 2
    assert len(again["calls"]) == 2
