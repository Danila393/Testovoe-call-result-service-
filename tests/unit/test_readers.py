from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.enums import ConsumerState, HealthStatus
from app.exceptions import CampaignNotFoundError, ServiceNotReadyError, StorageUnavailableError
from app.models import Call, Campaign, PageParams
from app.services.readers import CampaignCallsReader, HealthReader
from tests.fakes import InMemoryStores

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def stores() -> InMemoryStores:
    stores = InMemoryStores()
    stores.campaigns.items["camp_001"] = Campaign("camp_001", "Напоминание", T0)
    for i in range(3):
        call = Call(f"call_{i}", "camp_001", "79001234567", "success", T0 + timedelta(minutes=i))
        stores.calls.items[call.call_id] = call
    return stores


async def test_campaign_calls_page(stores: InMemoryStores) -> None:
    reader = CampaignCallsReader(stores.campaigns, stores.calls)
    response = await reader.read("camp_001", PageParams(limit=2, offset=1))
    assert response.total == 3
    assert [c.call_id for c in response.calls] == ["call_1", "call_2"]


async def test_missing_campaign_raises(stores: InMemoryStores) -> None:
    reader = CampaignCallsReader(stores.campaigns, stores.calls)
    with pytest.raises(CampaignNotFoundError) as info:
        await reader.read("camp_404", PageParams())
    assert info.value.campaign_id == "camp_404"


async def test_storage_failure_propagates(stores: InMemoryStores) -> None:
    stores.campaigns.fail_with = StorageUnavailableError("down")
    reader = CampaignCallsReader(stores.campaigns, stores.calls)
    with pytest.raises(StorageUnavailableError):
        await reader.read("camp_001", PageParams())


def make_health(mongo_ok: bool, state: ConsumerState) -> HealthReader:
    async def ping() -> bool:
        return mongo_ok

    return HealthReader(ping, lambda: state)


async def test_health_ready() -> None:
    report = await make_health(True, ConsumerState.CONSUMING).read()
    assert report.status is HealthStatus.OK
    assert report.model_dump(mode="json") == {
        "status": "ok",
        "mongodb": {"ok": True, "state": "up"},
        "consumer": {"ok": True, "state": "consuming"},
    }


@pytest.mark.parametrize(
    ("mongo_ok", "state"),
    [
        (False, ConsumerState.CONSUMING),
        (True, ConsumerState.BACKOFF),
        (False, ConsumerState.STOPPED),
    ],
)
async def test_health_not_ready_raises_with_report(mongo_ok: bool, state: ConsumerState) -> None:
    with pytest.raises(ServiceNotReadyError) as info:
        await make_health(mongo_ok, state).read()
    report = info.value.report
    assert report.status is HealthStatus.UNAVAILABLE
    assert report.mongodb.ok is mongo_ok
    assert report.consumer.state == state.value
