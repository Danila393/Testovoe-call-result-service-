from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from app.models import Call, Campaign
from app.repositories import MongoCallStore, MongoCampaignStore
from app.repositories.mongo import CALLS, CAMPAIGNS, Document

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


def make_call(call_id: str, campaign_id: str = "camp_001", minutes: int = 0) -> Call:
    return Call(call_id, campaign_id, "79001234567", "success", T0 + timedelta(minutes=minutes))


async def test_indexes_created(mongo_db: AsyncDatabase[Document]) -> None:
    campaign_indexes = await mongo_db[CAMPAIGNS].index_information()
    call_indexes = await mongo_db[CALLS].index_information()
    assert campaign_indexes["uniq_campaign_id"]["unique"] is True
    assert call_indexes["uniq_call_id"]["unique"] is True
    assert "campaign_created_call" in call_indexes


async def test_campaign_ensure_is_idempotent_and_first_write_wins(
    mongo_db: AsyncDatabase[Document],
) -> None:
    store = MongoCampaignStore(mongo_db)
    first = await store.ensure(Campaign("camp_001", "Первая", T0))
    second = await store.ensure(Campaign("camp_001", "Вторая", T0 + timedelta(days=1)))
    assert first == second == Campaign("camp_001", "Первая", T0)
    assert await mongo_db[CAMPAIGNS].count_documents({}) == 1
    assert await store.get("missing") is None


async def test_concurrent_campaign_upserts_create_single_document(
    mongo_db: AsyncDatabase[Document],
) -> None:
    store = MongoCampaignStore(mongo_db)
    results = await asyncio.gather(
        *(store.ensure(Campaign("camp_race", f"n{i}", T0)) for i in range(20))
    )
    assert len({r.name for r in results}) == 1
    assert await mongo_db[CAMPAIGNS].count_documents({"campaign_id": "camp_race"}) == 1


async def test_call_insert_and_duplicate(mongo_db: AsyncDatabase[Document]) -> None:
    store = MongoCallStore(mongo_db)
    call = make_call("call_0001")
    assert (await store.insert(call)).inserted is True
    dup = await store.insert(make_call("call_0001", minutes=5))
    assert dup.inserted is False
    assert dup.existing == call  # tz-aware UTC round-trip
    assert dup.existing.created_at.tzinfo is not None
    assert await mongo_db[CALLS].count_documents({}) == 1


async def test_list_filters_sorts_and_paginates(mongo_db: AsyncDatabase[Document]) -> None:
    store = MongoCallStore(mongo_db)
    await store.insert(make_call("call_b", minutes=1))
    await store.insert(make_call("call_a", minutes=1))
    await store.insert(make_call("call_c", minutes=0))
    await store.insert(make_call("call_x", campaign_id="camp_002"))

    page = await store.page_by_campaign("camp_001", limit=10, offset=0)
    assert [c.call_id for c in page.calls] == ["call_c", "call_a", "call_b"]
    assert page.total == 3
    second = await store.page_by_campaign("camp_001", limit=1, offset=1)
    assert [c.call_id for c in second.calls] == ["call_a"]
    assert second.total == 3
    beyond = await store.page_by_campaign("camp_001", limit=10, offset=50)
    assert (beyond.calls, beyond.total) == ([], 3)
    far = await store.page_by_campaign("camp_001", limit=1000, offset=1_000_000)
    assert (far.calls, far.total) == ([], 3)
    empty = await store.page_by_campaign("camp_404", limit=10, offset=0)
    assert (empty.calls, empty.total) == ([], 0)
