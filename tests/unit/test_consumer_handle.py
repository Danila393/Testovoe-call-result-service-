"""Ack/reject/nack decisions of the consumer, without a broker."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aio_pika.abc import AbstractIncomingMessage

from app.config import Settings
from app.consumer import CallConsumer
from app.repository import StorageUnavailableError
from app.service import CallIngestService, IngestResult, Outcome
from tests.factories import message_bytes
from tests.fakes import InMemoryCallStore, InMemoryCampaignStore


class FakeMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.delivery_tag = 1
        self.redelivered = False
        self.settled: list[tuple[str, Any]] = []

    async def ack(self) -> None:
        self.settled.append(("ack", None))

    async def reject(self, requeue: bool = False) -> None:
        self.settled.append(("reject", requeue))

    async def nack(self, requeue: bool = True) -> None:
        self.settled.append(("nack", requeue))


async def handle(consumer: CallConsumer, message: FakeMessage) -> None:
    await consumer._handle(cast("AbstractIncomingMessage", message))


@pytest.fixture
def stores():
    return InMemoryCampaignStore(), InMemoryCallStore()


@pytest.fixture
def consumer(stores):
    return CallConsumer(Settings(retry_delay_seconds=0), CallIngestService(*stores))


async def test_valid_message_acked_after_write(consumer, stores):
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert msg.settled == [("ack", None)]
    assert "call_0001" in stores[1].items


async def test_duplicate_acked(consumer):
    await handle(consumer, FakeMessage(message_bytes()))
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert msg.settled == [("ack", None)]


@pytest.mark.parametrize("body", [b"{broken", message_bytes(status="BAD STATUS")])
async def test_invalid_message_rejected_without_requeue(consumer, stores, body):
    msg = FakeMessage(body)
    await handle(consumer, msg)
    assert msg.settled == [("reject", False)]
    assert stores[1].items == {}


async def test_conflict_rejected_without_requeue(consumer):
    await handle(consumer, FakeMessage(message_bytes()))
    msg = FakeMessage(message_bytes(phone="79990000000"))
    await handle(consumer, msg)
    assert msg.settled == [("reject", False)]


async def test_storage_outage_retried_in_place_then_acked(stores):
    campaigns, calls = stores
    attempts = 0
    inner = CallIngestService(campaigns, calls)

    class FlakyStorage:
        async def ingest(self, body: bytes) -> IngestResult:
            nonlocal attempts
            attempts += 1
            if attempts < 4:
                raise StorageUnavailableError("mongo down")
            return await inner.ingest(body)

    consumer = CallConsumer(Settings(retry_delay_seconds=0), FlakyStorage())
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert attempts == 4
    assert msg.settled == [("ack", None)]  # never nacked: delivery count is not consumed
    assert "call_0001" in calls.items


async def test_non_transient_storage_error_nacked_with_requeue(consumer, stores):
    stores[1].fail_with = ConnectionError("unexpected")
    msg = FakeMessage(message_bytes())
    await handle(consumer, msg)
    assert msg.settled == [("nack", True)]
    assert stores[1].items == {}


async def test_unexpected_exception_does_not_escape():
    class Exploding:
        async def ingest(self, body: bytes) -> IngestResult:
            raise ZeroDivisionError

    consumer = CallConsumer(Settings(retry_delay_seconds=0), Exploding())
    msg = FakeMessage(b"{}")
    await handle(consumer, msg)
    assert msg.settled == [("nack", True)]


def test_outcome_ack_matrix():
    assert {o for o in Outcome if o.should_ack} == {Outcome.STORED, Outcome.DUPLICATE}
