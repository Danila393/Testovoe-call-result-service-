from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import (
    AutoReconnect,
    DuplicateKeyError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from app.exceptions import StorageUnavailableError
from app.models import Call
from app.repositories import MongoCallStore
from app.repositories.mongo import Document, translate_errors


@pytest.mark.parametrize(
    "exc", [ServerSelectionTimeoutError("no servers"), AutoReconnect("primary stepped down")]
)
async def test_transient_errors_translated(exc: PyMongoError) -> None:
    with pytest.raises(StorageUnavailableError):
        async with translate_errors():
            raise exc


async def test_retryable_write_label_translated() -> None:
    exc = OperationFailure("write conflict", code=112)
    exc._add_error_label("RetryableWriteError")
    with pytest.raises(StorageUnavailableError):
        async with translate_errors():
            raise exc


@pytest.mark.parametrize(
    "exc", [DuplicateKeyError("dup", code=11000), OperationFailure("bad query", code=2)]
)
async def test_non_transient_errors_pass_through(exc: PyMongoError) -> None:
    with pytest.raises(type(exc)):
        async with translate_errors():
            raise exc


async def test_unreachable_server_raises_storage_unavailable() -> None:
    client: AsyncMongoClient[Document] = AsyncMongoClient(
        "mongodb://127.0.0.1:1", serverSelectionTimeoutMS=100, tz_aware=True
    )
    store = MongoCallStore(client["unreachable"])
    call = Call("c1", "camp", "79001234567", "success", datetime.now(timezone.utc))
    try:
        with pytest.raises(StorageUnavailableError):
            await store.insert(call)
    finally:
        await client.close()
