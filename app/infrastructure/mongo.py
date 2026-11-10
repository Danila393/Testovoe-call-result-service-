"""MongoDB client construction and index management."""

from __future__ import annotations

from pymongo import ASCENDING, AsyncMongoClient, IndexModel
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.repositories.mongo import CALLS, CAMPAIGNS, Document


def create_client(settings: Settings) -> AsyncMongoClient[Document]:
    # tz_aware: dates come back as aware UTC datetimes, matching what we validate and store.
    return AsyncMongoClient(
        settings.mongodb_url,
        tz_aware=True,
        serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
        connectTimeoutMS=settings.mongodb_timeout_ms,
        appname="call-results-service",
    )


async def ensure_indexes(db: AsyncDatabase[Document]) -> None:
    """Create indexes the service relies on for idempotency and query speed. Idempotent."""
    await db[CAMPAIGNS].create_indexes(
        [IndexModel([("campaign_id", ASCENDING)], unique=True, name="uniq_campaign_id")]
    )
    await db[CALLS].create_indexes(
        [
            IndexModel([("call_id", ASCENDING)], unique=True, name="uniq_call_id"),
            IndexModel(
                [("campaign_id", ASCENDING), ("created_at", ASCENDING), ("call_id", ASCENDING)],
                name="campaign_created_call",
            ),
        ]
    )


async def ping(client: AsyncMongoClient[Document]) -> bool:
    try:
        await client.admin.command("ping")
    except Exception:  # noqa: BLE001 - health probe: any failure means "unavailable"
        return False
    return True
