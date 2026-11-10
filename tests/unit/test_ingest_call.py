from __future__ import annotations

import logging

import pytest

from app.enums import IngestOutcome
from app.exceptions import StorageUnavailableError
from app.models import IngestCallCommand
from app.services.commands import IngestCallHandler
from tests.factories import message_bytes
from tests.fakes import InMemoryStores


@pytest.fixture
def stores() -> InMemoryStores:
    return InMemoryStores()


@pytest.fixture
def handler(stores: InMemoryStores) -> IngestCallHandler:
    return IngestCallHandler(stores.campaigns, stores.calls)


def cmd(body: bytes) -> IngestCallCommand:
    return IngestCallCommand(body)


async def test_stores_campaign_and_call(handler: IngestCallHandler, stores: InMemoryStores) -> None:
    result = await handler.handle(cmd(message_bytes()))
    assert result.outcome is IngestOutcome.STORED
    assert result.outcome.should_ack
    assert set(stores.campaigns.items) == {"camp_001"}
    assert set(stores.calls.items) == {"call_0001"}


async def test_second_call_reuses_campaign(
    handler: IngestCallHandler, stores: InMemoryStores
) -> None:
    await handler.handle(cmd(message_bytes()))
    result = await handler.handle(cmd(message_bytes(call_id="call_0002")))
    assert result.outcome is IngestOutcome.STORED
    assert len(stores.campaigns.items) == 1
    assert len(stores.calls.items) == 2


async def test_exact_redelivery_is_duplicate_and_acked(
    handler: IngestCallHandler, stores: InMemoryStores
) -> None:
    await handler.handle(cmd(message_bytes()))
    result = await handler.handle(cmd(message_bytes()))
    assert result.outcome is IngestOutcome.DUPLICATE
    assert result.outcome.should_ack
    assert len(stores.calls.items) == 1


async def test_same_call_id_with_other_data_is_conflict(
    handler: IngestCallHandler, stores: InMemoryStores, caplog: pytest.LogCaptureFixture
) -> None:
    await handler.handle(cmd(message_bytes()))
    with caplog.at_level(logging.ERROR):
        result = await handler.handle(cmd(message_bytes(status="failed")))
    assert result.outcome is IngestOutcome.CONFLICT
    assert not result.outcome.should_ack
    assert stores.calls.items["call_0001"].status == "success"
    assert "conflicting duplicate" in caplog.text


async def test_campaign_name_change_keeps_first(
    handler: IngestCallHandler, stores: InMemoryStores, caplog: pytest.LogCaptureFixture
) -> None:
    await handler.handle(cmd(message_bytes()))
    with caplog.at_level(logging.WARNING):
        result = await handler.handle(
            cmd(message_bytes(call_id="call_0002", campaign_name="Другое"))
        )
    assert result.outcome is IngestOutcome.STORED
    assert stores.campaigns.items["camp_001"].name == "Напоминание о платеже"
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
async def test_invalid_messages_are_logged_and_not_stored(
    handler: IngestCallHandler,
    stores: InMemoryStores,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = await handler.handle(cmd(body))
    assert result.outcome is IngestOutcome.INVALID
    assert not result.outcome.should_ack
    assert result.reason
    assert stores.campaigns.items == {}
    assert stores.calls.items == {}
    assert "invalid message rejected" in caplog.text


async def test_storage_errors_propagate(handler: IngestCallHandler, stores: InMemoryStores) -> None:
    stores.calls.fail_with = StorageUnavailableError("down")
    with pytest.raises(StorageUnavailableError):
        await handler.handle(cmd(message_bytes()))


def test_outcome_ack_matrix() -> None:
    assert {o for o in IngestOutcome if o.should_ack} == {
        IngestOutcome.STORED,
        IngestOutcome.DUPLICATE,
    }
