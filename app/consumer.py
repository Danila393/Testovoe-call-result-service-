"""RabbitMQ consumer running as a background task inside the FastAPI process.

Lifecycle and ack semantics: docs/ARCHITECTURE.md §6-7.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

import aio_pika
from aio_pika.abc import AbstractConnection, AbstractIncomingMessage

from app.config import Settings
from app.messaging import declare_topology
from app.repository import StorageUnavailableError
from app.service import IngestResult

logger = logging.getLogger(__name__)

Connector = Callable[[str], Awaitable[AbstractConnection]]


class Ingestor(Protocol):
    async def ingest(self, body: bytes) -> IngestResult: ...


class ConsumerState(str, enum.Enum):
    CREATED = "created"
    CONNECTING = "connecting"
    CONSUMING = "consuming"
    BACKOFF = "backoff"
    STOPPED = "stopped"


async def _default_connect(url: str) -> AbstractConnection:
    return await aio_pika.connect(url, timeout=10)


class CallConsumer:
    def __init__(
        self,
        settings: Settings,
        ingestor: Ingestor,
        connect: Connector = _default_connect,
    ) -> None:
        self._settings = settings
        self._ingestor = ingestor
        self._connect = connect
        self._state = ConsumerState.CREATED
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def state(self) -> ConsumerState:
        return self._state

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("consumer already started")
        self._task = asyncio.create_task(self._run(), name="call-consumer")

    async def stop(self, timeout: float = 10.0) -> None:
        """Finish the message in progress (up to ``timeout``), then disconnect.

        Messages received but not yet acked are returned to the queue by RabbitMQ when the
        channel closes; ingestion is idempotent, so redelivery is safe.
        """
        self._stopping = True
        if self._task is None:
            self._state = ConsumerState.STOPPED
            return
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except asyncio.TimeoutError:
            logger.warning("message still in progress at shutdown; it will be redelivered")
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._state = ConsumerState.STOPPED
        logger.info("consumer stopped")

    async def _run(self) -> None:
        delay = self._settings.reconnect_initial_delay_seconds
        while not self._stopping:
            self._state = ConsumerState.CONNECTING
            try:
                await self._consume_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any broker failure leads to reconnect
                logger.warning(
                    "rabbitmq unavailable, reconnecting",
                    extra={"error": repr(exc), "retry_in_seconds": delay},
                )
            else:
                if self._stopping:
                    break
                logger.warning("rabbitmq connection closed, reconnecting")
            if self._state is ConsumerState.CONSUMING:
                # The previous session worked: start backoff from scratch.
                delay = self._settings.reconnect_initial_delay_seconds
            self._state = ConsumerState.BACKOFF
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._settings.reconnect_max_delay_seconds)

    async def _consume_once(self) -> None:
        connection = await self._connect(self._settings.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=self._settings.prefetch_count)
            queue = await declare_topology(channel)
            self._state = ConsumerState.CONSUMING
            logger.info("consuming", extra={"queue": queue.name})
            async with queue.iterator() as messages:
                async for message in messages:
                    if self._stopping:
                        break  # not acked → redelivered after the channel closes
                    self._idle.clear()
                    try:
                        await self._handle(message)
                    finally:
                        self._idle.set()

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        context = {"delivery_tag": message.delivery_tag, "redelivered": message.redelivered}
        delay = self._settings.retry_delay_seconds
        while True:
            try:
                result = await self._ingestor.ingest(message.body)
                break
            except StorageUnavailableError as exc:
                # The database is down, not the message is bad: hold the message and retry in
                # place, so an outage does not burn through the queue's delivery limit.
                logger.warning(
                    "storage unavailable, retrying message",
                    extra={**context, "error": str(exc), "retry_in_seconds": delay},
                )
                await asyncio.sleep(delay)
                delay = min(max(delay * 2, 0.1), self._settings.storage_retry_max_delay_seconds)
            except Exception:
                # Unexpected failure: requeue; x-delivery-limit dead-letters a poison message.
                logger.exception(
                    "processing failed, message will be requeued",
                    extra={**context, "retry_in_seconds": self._settings.retry_delay_seconds},
                )
                await asyncio.sleep(self._settings.retry_delay_seconds)
                await message.nack(requeue=True)
                return

        if result.outcome.should_ack:
            await message.ack()
        else:
            # Dead-lettered to calls.results.dead (see app.messaging).
            await message.reject(requeue=False)
        logger.debug(
            "message settled",
            extra={**context, "outcome": result.outcome.value, "call_id": result.call_id},
        )
