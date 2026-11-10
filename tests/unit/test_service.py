from __future__ import annotations

import logging

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.service import CallIngestService, Outcome
from tests.factories import message_bytes
from tests.fakes import InMemoryCallStore, InMemoryCampaignStore


@pytest.fixture
def stores():
    return InMemoryCampaignStore(), InMemoryCallStore()


@pytest.fixture
def service(stores):
    return CallIngestService(*stores)


async def test_stores_campaign_and_call(service, stores):
    campaigns, calls = stores
    result = await service.ingest(message_bytes())
    assert result.outcome is Outcome.STORED
    assert result.outcome.should_ack
    assert set(campaigns.items) == {"camp_001"}
    assert set(calls.items) == {"call_0001"}


async def test_second_call_reuses_campaign(service, stores):
    campaigns, calls = stores
    await service.ingest(message_bytes())
    result = await service.ingest(message_bytes(call_id="call_0002"))
    assert result.outcome is Outcome.STORED
    assert len(campaigns.items) == 1
    assert len(calls.items) == 2


async def test_exact_redelivery_is_duplicate_and_acked(service, stores):
    await service.ingest(message_bytes())
    result = await service.ingest(message_bytes())
    assert result.outcome is Outcome.DUPLICATE
    assert result.outcome.should_ack
    assert len(stores[1].items) == 1


async def test_same_call_id_with_other_data_is_conflict(service, stores, caplog):
    await service.ingest(message_bytes())
    with caplog.at_level(logging.ERROR):
        result = await service.ingest(message_bytes(status="failed"))
    assert result.outcome is Outcome.CONFLICT
    assert not result.outcome.should_ack
    assert stores[1].items["call_0001"].status == "success"
    assert "conflicting duplicate" in caplog.text


async def test_campaign_name_change_keeps_first(service, stores, caplog):
    await service.ingest(message_bytes())
    with caplog.at_level(logging.WARNING):
        result = await service.ingest(message_bytes(call_id="call_0002", campaign_name="Другое"))
    assert result.outcome is Outcome.STORED
    assert stores[0].items["camp_001"].name == "Напоминание о платеже"
    assert "campaign name differs" in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"\xff\xfe\x00garbage",
        b"[1, 2]",
        b'"string"',
        message_bytes(phone="abc"),
        message_bytes(created_at="2026-10-20T10:06:00"),
    ],
)
async def test_invalid_messages_are_logged_and_not_stored(service, stores, caplog, body):
    with caplog.at_level(logging.WARNING):
        result = await service.ingest(body)
    assert result.outcome is Outcome.INVALID
    assert not result.outcome.should_ack
    assert result.reason
    assert stores[0].items == {}
    assert stores[1].items == {}
    assert "invalid message rejected" in caplog.text


async def test_storage_errors_propagate(service, stores):
    stores[1].fail_with = ServerSelectionTimeoutError("down")
    with pytest.raises(ServerSelectionTimeoutError):
        await service.ingest(message_bytes())
