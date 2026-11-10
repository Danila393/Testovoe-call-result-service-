"""Persistence: storage protocols and their MongoDB implementation."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Protocol

from pymongo import ASCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.models import Call, Campaign

CAMPAIGNS = "campaigns"
CALLS = "calls"

Document = dict[str, Any]


@dataclass(frozen=True, slots=True)
class InsertCallResult:
    """Result of inserting a call.

    ``inserted`` is True when the call was written now; otherwise ``existing`` is the stored one.
    """

    inserted: bool
    existing: Call | None = None


class CampaignStore(Protocol):
    async def ensure(self, campaign: Campaign) -> Campaign:
        """Create the campaign if absent. Returns the stored campaign (first write wins)."""

    async def get(self, campaign_id: str) -> Campaign | None: ...


class CallStore(Protocol):
    async def insert(self, call: Call) -> InsertCallResult: ...

    async def list_by_campaign(
        self, campaign_id: str, *, limit: int, offset: int
    ) -> list[Call]: ...

    async def count_by_campaign(self, campaign_id: str) -> int: ...


def _campaign_from_doc(doc: Document) -> Campaign:
    return Campaign(campaign_id=doc["campaign_id"], name=doc["name"], created_at=doc["created_at"])


def _call_from_doc(doc: Document) -> Call:
    return Call(
        call_id=doc["call_id"],
        campaign_id=doc["campaign_id"],
        phone=doc["phone"],
        status=doc["status"],
        created_at=doc["created_at"],
    )


_CAMPAIGN_PROJECTION = {"_id": False, "campaign_id": True, "name": True, "created_at": True}
_CALL_PROJECTION = {
    "_id": False,
    "call_id": True,
    "campaign_id": True,
    "phone": True,
    "status": True,
    "created_at": True,
}


class MongoCampaignStore:
    def __init__(self, db: AsyncDatabase[Document]) -> None:
        self._col: AsyncCollection[Document] = db[CAMPAIGNS]

    async def ensure(self, campaign: Campaign) -> Campaign:
        # DuplicateKeyError: a concurrent upsert created it between our match and insert,
        # which is exactly the outcome we want.
        with contextlib.suppress(DuplicateKeyError):
            await self._col.update_one(
                {"campaign_id": campaign.campaign_id},
                {"$setOnInsert": {"name": campaign.name, "created_at": campaign.created_at}},
                upsert=True,
            )
        stored = await self.get(campaign.campaign_id)
        if stored is None:  # pragma: no cover - would mean the document vanished right after upsert
            raise RuntimeError(f"campaign {campaign.campaign_id!r} missing after upsert")
        return stored

    async def get(self, campaign_id: str) -> Campaign | None:
        doc = await self._col.find_one({"campaign_id": campaign_id}, _CAMPAIGN_PROJECTION)
        return _campaign_from_doc(doc) if doc is not None else None


class MongoCallStore:
    def __init__(self, db: AsyncDatabase[Document]) -> None:
        self._col: AsyncCollection[Document] = db[CALLS]

    async def insert(self, call: Call) -> InsertCallResult:
        try:
            await self._col.insert_one(
                {
                    "call_id": call.call_id,
                    "campaign_id": call.campaign_id,
                    "phone": call.phone,
                    "status": call.status,
                    "created_at": call.created_at,
                }
            )
        except DuplicateKeyError:
            doc = await self._col.find_one({"call_id": call.call_id}, _CALL_PROJECTION)
            if doc is None:  # pragma: no cover - unique index violated by a doc that is gone
                raise
            return InsertCallResult(inserted=False, existing=_call_from_doc(doc))
        return InsertCallResult(inserted=True)

    async def list_by_campaign(self, campaign_id: str, *, limit: int, offset: int) -> list[Call]:
        cursor = (
            self._col.find({"campaign_id": campaign_id}, _CALL_PROJECTION)
            .sort([("created_at", ASCENDING), ("call_id", ASCENDING)])
            .skip(offset)
            .limit(limit)
        )
        return [_call_from_doc(doc) async for doc in cursor]

    async def count_by_campaign(self, campaign_id: str) -> int:
        return await self._col.count_documents({"campaign_id": campaign_id})
