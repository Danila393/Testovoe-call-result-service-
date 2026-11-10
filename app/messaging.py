"""RabbitMQ topology - the single source of truth for names and queue arguments.

``producer.py`` declares the main queue too (it is standalone and does not import this module);
``tests/unit/test_topology.py`` checks that both declarations stay identical.
"""

from __future__ import annotations

from typing import Final

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractQueue

EXCHANGE: Final = "calls"
ROUTING_KEY: Final = "call.result"
QUEUE: Final = "calls.results"
DEAD_LETTER_EXCHANGE: Final = "calls.dlx"
DEAD_LETTER_QUEUE: Final = "calls.results.dead"
DELIVERY_LIMIT: Final = 5

QUEUE_ARGUMENTS: Final[dict[str, str | int]] = {
    "x-queue-type": "quorum",
    "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
    "x-delivery-limit": DELIVERY_LIMIT,
}


async def declare_topology(channel: AbstractChannel) -> AbstractQueue:
    """Declare exchanges, queues and bindings (idempotent). Returns the main queue."""
    dlx = await channel.declare_exchange(
        DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True
    )
    dead = await channel.declare_queue(DEAD_LETTER_QUEUE, durable=True)
    await dead.bind(dlx)

    exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(QUEUE, durable=True, arguments=dict(QUEUE_ARGUMENTS))
    await queue.bind(exchange, routing_key=ROUTING_KEY)
    return queue
