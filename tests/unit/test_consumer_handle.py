"""Ack/reject/nack decisions of the consumer, without a broker."""

from __future__ import annotations

from typing import cast

import pytest
from aio_pika.abc import AbstractIncomingMessage

from app.config import Settings
from app.consumers import CallConsumer
from app.exceptions import StorageUnavailableError
from app.models import IngestCallCommand, IngestResult
from app.services.commands import IngestCallHandler
from tests.factories import message_bytes
from tests.fakes import InMemoryStores

Settled = tuple[str, bool | None]


class FakeMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.delivery_tag = 1
        self.redelivered = False
        self.settled: list[Settled] = []

    async def ack(self) -> None:
        self.settled.append(("ack", None))

    async def reject(self, requeue: bool = False) -> None:
        self.settled.append(("reject", requeue))

    async def nack(self, requeue: bool = True) -> None:
        self.settled.append(("nack", requeue))


async def handle(consumer: CallConsumer, message: FakeMessage) -> None:
    await consumer._handle(cast("AbstractIncomingMessage", message))


@pytest.fixture
def stores() -> InMemoryStores:
    return InMemoryStores()


@pytest.fixture
def consumer(stores: InMemoryStores) -> CallConsumer:
    handler = IngestCallHandler(stores.campaigns, stores.calls)
    return CallConsumer(Settings(retry_delay_seconds=0), handler)


async def test_valid_message_acked_after_write(
    consumer: CallConsumer, stores: InMemoryStores
) -> None:
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert msg.settled == [("ack", None)]
    assert "call_0001" in stores.calls.items


async def test_duplicate_acked(consumer: CallConsumer) -> None:
    await handle(consumer, FakeMessage(message_bytes()))
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert msg.settled == [("ack", None)]


@pytest.mark.parametrize("body", [b"{broken", message_bytes(status="BAD STATUS")])
async def test_invalid_message_rejected_without_requeue(
    consumer: CallConsumer, stores: InMemoryStores, body: bytes
) -> None:
    msg = FakeMessage(body)
    await handle(consumer, msg)
    assert msg.settled == [("reject", False)]
    assert stores.calls.items == {}


async def test_conflict_rejected_without_requeue(consumer: CallConsumer) -> None:
    await handle(consumer, FakeMessage(message_bytes()))
    msg = FakeMessage(message_bytes(phone="79990000000"))
    await handle(consumer, msg)
    assert msg.settled == [("reject", False)]


async def test_storage_outage_retried_in_place_then_acked(stores: InMemoryStores) -> None:
    attempts = 0
    inner = IngestCallHandler(stores.campaigns, stores.calls)

    class FlakyStorage:
        async def handle(self, command: IngestCallCommand) -> IngestResult:
            nonlocal attempts
            attempts += 1
            if attempts < 4:
                raise StorageUnavailableError("mongo down")
            return await inner.handle(command)

    consumer = CallConsumer(Settings(retry_delay_seconds=0), FlakyStorage())
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert attempts == 4
    assert msg.settled == [("ack", None)]  # never nacked: delivery count is not consumed
    assert "call_0001" in stores.calls.items


async def test_non_transient_storage_error_nacked_with_requeue(
    consumer: CallConsumer, stores: InMemoryStores
) -> None:
    stores.calls.fail_with = ConnectionError("unexpected")
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert msg.settled == [("nack", True)]
    assert stores.calls.items == {}


async def test_unexpected_exception_does_not_escape() -> None:
    class Exploding:
        async def handle(self, command: IngestCallCommand) -> IngestResult:
            raise ZeroDivisionError

    consumer = CallConsumer(Settings(retry_delay_seconds=0), Exploding())
    msg = FakeMessage(b"{}")
    await handle(consumer, msg)
    assert msg.settled == [("nack", True)]
