"""Persistence: storage protocols and their MongoDB implementation."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import (
    ConnectionFailure,
    DuplicateKeyError,
    ExecutionTimeout,
    PyMongoError,
    WTimeoutError,
)

from app.models import Call, Campaign

CAMPAIGNS = "campaigns"
CALLS = "calls"

Document = dict[str, Any]


class StorageUnavailableError(Exception):
    """The database is temporarily unreachable; the same operation may succeed later."""


def _is_transient(exc: PyMongoError) -> bool:
    return isinstance(exc, (ConnectionFailure, ExecutionTimeout, WTimeoutError)) or (
        exc.has_error_label("RetryableWriteError")
    )


@contextlib.asynccontextmanager
async def _translate_errors() -> AsyncIterator[None]:
    try:
        yield
    except DuplicateKeyError:
        raise
    except PyMongoError as exc:
        if _is_transient(exc):
            raise StorageUnavailableError(str(exc)) from exc
        raise


@dataclass(frozen=True, slots=True)
class InsertCallResult:
    """Result of inserting a call.

    ``inserted`` is True when the call was written now; otherwise ``existing`` is the stored one.
    """

    inserted: bool
    existing: Call | None = None


@dataclass(frozen=True, slots=True)
class CallPage:
    calls: list[Call]
    total: int


class CampaignStore(Protocol):
    """Implementations raise ``StorageUnavailableError`` for transient failures."""

    async def ensure(self, campaign: Campaign) -> Campaign:
        """Create the campaign if absent. Returns the stored campaign (first write wins)."""

    async def get(self, campaign_id: str) -> Campaign | None: ...


class CallStore(Protocol):
    """Implementations raise ``StorageUnavailableError`` for transient failures."""

    async def insert(self, call: Call) -> InsertCallResult: ...

    async def page_by_campaign(self, campaign_id: str, *, limit: int, offset: int) -> CallPage:
        """One page of a campaign's calls and their total, read in a single query."""


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
        async with _translate_errors():
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
        async with _translate_errors():
            doc = await self._col.find_one({"campaign_id": campaign_id}, _CAMPAIGN_PROJECTION)
        return _campaign_from_doc(doc) if doc is not None else None


class MongoCallStore:
    def __init__(self, db: AsyncDatabase[Document]) -> None:
        self._col: AsyncCollection[Document] = db[CALLS]

    async def insert(self, call: Call) -> InsertCallResult:
        document = {
            "call_id": call.call_id,
            "campaign_id": call.campaign_id,
            "phone": call.phone,
            "status": call.status,
            "created_at": call.created_at,
        }
        async with _translate_errors():
            try:
                await self._col.insert_one(document)
            except DuplicateKeyError:
                doc = await self._col.find_one({"call_id": call.call_id}, _CALL_PROJECTION)
                if doc is None:  # pragma: no cover - unique index hit by a doc that is now gone
                    raise
                return InsertCallResult(inserted=False, existing=_call_from_doc(doc))
        return InsertCallResult(inserted=True)

    async def page_by_campaign(self, campaign_id: str, *, limit: int, offset: int) -> CallPage:
        # $facet computes the page and the total in one aggregate, so they cannot disagree
        # because of a write landing between two separate queries.
        pipeline: list[Document] = [
            {"$match": {"campaign_id": campaign_id}},
            # Sorting before $facet lets $match+$sort use the campaign_created_call index.
            {"$sort": {"created_at": 1, "call_id": 1}},
            {
                "$facet": {
                    "calls": [
                        {"$skip": offset},
                        {"$limit": limit},
                        {"$project": _CALL_PROJECTION},
                    ],
                    "total": [{"$count": "n"}],
                }
            },
        ]
        async with _translate_errors():
            cursor = await self._col.aggregate(pipeline)
            result = await cursor.to_list(length=1)
        facet = result[0]
        total = facet["total"][0]["n"] if facet["total"] else 0
        return CallPage(calls=[_call_from_doc(d) for d in facet["calls"]], total=total)
