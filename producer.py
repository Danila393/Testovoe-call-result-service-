"""Publish demo call results to RabbitMQ: 2 calls for each of 2 campaigns.

Standalone script: depends only on ``aio-pika`` (``pip install -r requirements-producer.txt``).

    python producer.py                      # amqp://guest:guest@localhost:5672/
    RABBITMQ_URL=amqp://u:p@host:5672/ python producer.py

Call ids are fixed, so running the script again does not create duplicates: the service
treats re-sent identical calls as already stored.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from typing import Any, Final

try:
    import aio_pika
except ImportError:  # pragma: no cover - guidance for running on a bare host
    sys.exit("aio-pika is not installed. Run: pip install -r requirements-producer.txt")

# Must match app/messaging.py (checked by tests/unit/test_topology.py).
EXCHANGE: Final = "calls"
ROUTING_KEY: Final = "call.result"
QUEUE: Final = "calls.results"
QUEUE_ARGUMENTS: Final[dict[str, str | int]] = {
    "x-queue-type": "quorum",
    "x-dead-letter-exchange": "calls.dlx",
    "x-delivery-limit": 5,
}

DEFAULT_URL: Final = "amqp://guest:guest@localhost:5672/"

MESSAGES: Final[list[dict[str, Any]]] = [
    {
        "call_id": "call_0001",
        "campaign_id": "camp_001",
        "campaign_name": "Напоминание о платеже",
        "campaign_created_at": "2026-10-20T10:00:00Z",
        "phone": "79001234567",
        "status": "success",
        "created_at": "2026-10-20T10:06:00Z",
    },
    {
        "call_id": "call_0002",
        "campaign_id": "camp_001",
        "campaign_name": "Напоминание о платеже",
        "campaign_created_at": "2026-10-20T10:00:00Z",
        "phone": "79001234568",
        "status": "no_answer",
        "created_at": "2026-10-20T10:07:30Z",
    },
    {
        "call_id": "call_0003",
        "campaign_id": "camp_002",
        "campaign_name": "Опрос удовлетворённости",
        "campaign_created_at": "2026-10-21T09:00:00Z",
        "phone": "79001234569",
        "status": "success",
        "created_at": "2026-10-21T09:15:00Z",
    },
    {
        "call_id": "call_0004",
        "campaign_id": "camp_002",
        "campaign_name": "Опрос удовлетворённости",
        "campaign_created_at": "2026-10-21T09:00:00Z",
        "phone": "79001234570",
        "status": "busy",
        "created_at": "2026-10-21T09:16:10Z",
    },
]


async def publish(url: str, messages: list[dict[str, Any]]) -> int:
    """Publish ``messages`` with publisher confirms; raises if any is not routed or confirmed."""
    connection = await aio_pika.connect(url, timeout=10)
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        exchange = await channel.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        queue = await channel.declare_queue(QUEUE, durable=True, arguments=dict(QUEUE_ARGUMENTS))
        await queue.bind(exchange, routing_key=ROUTING_KEY)

        for body in messages:
            message = aio_pika.Message(
                body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                content_type="application/json",
                content_encoding="utf-8",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=str(body["call_id"]),
                app_id="producer.py",
            )
            # mandatory=True: an unroutable message raises instead of being silently dropped.
            await exchange.publish(message, routing_key=ROUTING_KEY, mandatory=True)
            print(f"published {body['call_id']} -> {body['campaign_id']}")
    return len(messages)


def _make_console_safe() -> None:
    """Never crash on output encoding (e.g. a localized OS error on a legacy Windows code page)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def main() -> int:
    _make_console_safe()
    url = os.environ.get("RABBITMQ_URL", DEFAULT_URL)
    try:
        count = asyncio.run(publish(url, MESSAGES))
    except (OSError, aio_pika.exceptions.AMQPError) as exc:
        print(f"failed to publish to RabbitMQ: {exc!r}", file=sys.stderr)
        return 1
    print(f"done: {count} messages confirmed by RabbitMQ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
