"""Consumer against a real RabbitMQ (storage is in-memory or real MongoDB depending on the test)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

import aio_pika
import pytest
from pymongo.asynchronous.database import AsyncDatabase

import producer
from app.config import Settings
from app.consumers import CallConsumer
from app.consumers.call_consumer import Connector, IngestCommandHandler
from app.enums import ConsumerState
from app.exceptions import StorageUnavailableError
from app.infrastructure.rabbitmq import DEAD_LETTER_QUEUE, DELIVERY_LIMIT, QUEUE, declare_topology
from app.models import IngestCallCommand, IngestResult
from app.repositories import MongoCallStore, MongoCampaignStore
from app.repositories.mongo import CALLS, CAMPAIGNS, Document
from app.services.commands import IngestCallHandler
from tests.factories import message, task_format_message
from tests.fakes import InMemoryCallStore, InMemoryCampaignStore

Channel = aio_pika.abc.AbstractChannel
Connection = aio_pika.abc.AbstractConnection
StartConsumer = Callable[..., CallConsumer]

pytestmark = pytest.mark.integration


async def wait_until(predicate: Callable[[], Awaitable[bool]], timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


@pytest.fixture
async def broker(rabbitmq: Connection) -> AsyncIterator[Channel]:
    """A channel with the topology declared and both queues purged."""
    channel = await rabbitmq.channel()
    await declare_topology(channel)
    for name in (QUEUE, DEAD_LETTER_QUEUE):
        await (await channel.get_queue(name)).purge()
    yield channel
    for name in (QUEUE, DEAD_LETTER_QUEUE):
        await (await channel.get_queue(name)).purge()


async def queue_depth(channel: Channel, name: str) -> int:
    declared = await channel.declare_queue(name, passive=True)
    return int(declared.declaration_result.message_count or 0)


async def publish_raw(settings: Settings, *bodies: bytes) -> None:
    connection = await aio_pika.connect(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        exchange = await channel.get_exchange(producer.EXCHANGE)
        for body in bodies:
            await exchange.publish(
                aio_pika.Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key=producer.ROUTING_KEY,
            )


@pytest.fixture
async def running(settings: Settings) -> AsyncIterator[StartConsumer]:
    started: list[CallConsumer] = []

    def start(handler: IngestCommandHandler, connect: Connector | None = None) -> CallConsumer:
        consumer = (
            CallConsumer(settings, handler, connect)
            if connect is not None
            else CallConsumer(settings, handler)
        )
        consumer.start()
        started.append(consumer)
        return consumer

    yield start
    for consumer in started:
        await consumer.stop()


async def test_producer_messages_end_up_in_mongo(
    settings: Settings, broker: Channel, mongo_db: AsyncDatabase[Document], running: StartConsumer
) -> None:
    consumer = running(IngestCallHandler(MongoCampaignStore(mongo_db), MongoCallStore(mongo_db)))
    assert await producer.publish(settings.rabbitmq_url, producer.MESSAGES) == 4

    async def all_stored() -> bool:
        return bool(await mongo_db[CALLS].count_documents({}) == 4)

    await wait_until(all_stored)
    assert consumer.state is ConsumerState.CONSUMING
    assert await mongo_db[CAMPAIGNS].count_documents({}) == 2
    assert await mongo_db[CALLS].count_documents({"campaign_id": "camp_001"}) == 2
    await wait_until(lambda: _is_zero(broker, QUEUE))

    # Re-running the producer is idempotent.
    await producer.publish(settings.rabbitmq_url, producer.MESSAGES)
    await wait_until(lambda: _is_zero(broker, QUEUE))
    assert await mongo_db[CALLS].count_documents({}) == 4


async def test_task_format_message_is_stored_in_mongo(
    settings: Settings,
    broker: Channel,
    mongo_db: AsyncDatabase[Document],
    running: StartConsumer,
) -> None:
    running(IngestCallHandler(MongoCampaignStore(mongo_db), MongoCallStore(mongo_db)))
    await publish_raw(settings, json.dumps(task_format_message()).encode())

    async def stored() -> bool:
        return bool(await mongo_db[CALLS].count_documents({"call_id": "call_0101"}) == 1)

    await wait_until(stored)
    campaign = await mongo_db[CAMPAIGNS].find_one({"campaign_id": "camp_003"})
    assert campaign is not None
    assert campaign["name"] == "camp_003"
    assert await queue_depth(broker, DEAD_LETTER_QUEUE) == 0


async def _is_zero(channel: Channel, name: str) -> bool:
    return await queue_depth(channel, name) == 0


async def test_invalid_messages_dead_lettered_and_consumer_keeps_working(
    settings: Settings, broker: Channel, running: StartConsumer
) -> None:
    calls = InMemoryCallStore()
    consumer = running(IngestCallHandler(InMemoryCampaignStore(), calls))
    await publish_raw(
        settings,
        b"not json",
        json.dumps(message(call_id="bad", phone="nope")).encode(),
        json.dumps(message(call_id="good_1")).encode(),
    )

    async def two_dead() -> bool:
        return await queue_depth(broker, DEAD_LETTER_QUEUE) == 2

    await wait_until(two_dead)
    await wait_until(lambda: _has(calls, "good_1"))
    assert consumer.state is ConsumerState.CONSUMING
    assert set(calls.items) == {"good_1"}


async def _has(calls: InMemoryCallStore, call_id: str) -> bool:
    return call_id in calls.items


async def test_storage_outage_holds_message_until_recovery(
    settings: Settings, broker: Channel, running: StartConsumer
) -> None:
    calls = InMemoryCallStore()
    calls.fail_with = StorageUnavailableError("mongo down")
    running(IngestCallHandler(InMemoryCampaignStore(), calls))
    await publish_raw(settings, json.dumps(message()).encode())

    # Much longer than delivery-limit x retry delay: an outage must not dead-letter messages.
    await asyncio.sleep(1.5)
    assert calls.items == {}
    assert await queue_depth(broker, DEAD_LETTER_QUEUE) == 0

    calls.fail_with = None
    await wait_until(lambda: _has(calls, "call_0001"))
    await wait_until(lambda: _is_zero(broker, QUEUE))
    assert await queue_depth(broker, DEAD_LETTER_QUEUE) == 0


async def test_poison_message_dead_lettered_after_delivery_limit(
    settings: Settings, broker: Channel, running: StartConsumer
) -> None:
    attempts = 0

    class Buggy:
        async def handle(self, command: IngestCallCommand) -> IngestResult:
            nonlocal attempts
            attempts += 1
            raise ZeroDivisionError("bug triggered by this message")

    running(Buggy())
    await publish_raw(settings, json.dumps(message()).encode())

    async def one_dead() -> bool:
        return await queue_depth(broker, DEAD_LETTER_QUEUE) == 1

    await wait_until(one_dead)
    # Exact count differs by one between RabbitMQ 3.x and 4.x semantics of x-delivery-limit.
    assert DELIVERY_LIMIT <= attempts <= DELIVERY_LIMIT + 1


async def test_reconnects_after_connection_loss(
    settings: Settings, broker: Channel, running: StartConsumer
) -> None:
    connections: list[Connection] = []

    async def tracking_connect(url: str) -> Connection:
        conn = await aio_pika.connect(url)
        connections.append(conn)
        return conn

    calls = InMemoryCallStore()
    consumer = running(IngestCallHandler(InMemoryCampaignStore(), calls), tracking_connect)

    async def consuming() -> bool:
        return consumer.state is ConsumerState.CONSUMING

    await wait_until(consuming)
    await connections[0].close()
    await wait_until(lambda: _len_at_least(connections, 2))
    await wait_until(consuming)

    await publish_raw(settings, json.dumps(message()).encode())
    await wait_until(lambda: _has(calls, "call_0001"))


async def _len_at_least(items: list[Connection], n: int) -> bool:
    return len(items) >= n


async def test_starts_while_broker_unreachable_then_recovers(
    settings: Settings, broker: Channel, running: StartConsumer
) -> None:
    failures = 0

    async def flaky_connect(url: str) -> Connection:
        nonlocal failures
        if failures < 2:
            failures += 1
            raise ConnectionRefusedError("broker not up yet")
        return await aio_pika.connect(url)

    consumer = running(
        IngestCallHandler(InMemoryCampaignStore(), InMemoryCallStore()), flaky_connect
    )
    await asyncio.sleep(0.05)
    assert consumer.state in (ConsumerState.BACKOFF, ConsumerState.CONNECTING)

    async def consuming() -> bool:
        return consumer.state is ConsumerState.CONSUMING

    await wait_until(consuming)
    assert failures == 2


async def test_stop_waits_for_message_in_progress(settings: Settings, broker: Channel) -> None:
    release = asyncio.Event()
    entered = asyncio.Event()
    finished: list[str] = []
    inner = IngestCallHandler(InMemoryCampaignStore(), InMemoryCallStore())

    class Slow:
        async def handle(self, command: IngestCallCommand) -> IngestResult:
            entered.set()
            await release.wait()
            result = await inner.handle(command)
            finished.append("done")
            return result

    consumer = CallConsumer(settings, Slow())
    consumer.start()
    await publish_raw(settings, json.dumps(message()).encode())
    await asyncio.wait_for(entered.wait(), 10)

    stop_task = asyncio.create_task(consumer.stop())
    await asyncio.sleep(0.1)
    assert not stop_task.done()
    release.set()
    await asyncio.wait_for(stop_task, 10)
    assert finished == ["done"]
    assert consumer.state is ConsumerState.STOPPED
    await wait_until(lambda: _is_zero(broker, QUEUE))  # it was acked, not requeued
