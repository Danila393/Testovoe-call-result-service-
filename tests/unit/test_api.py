"""HTTP layer: routes, dependencies and error mapping, with in-memory readers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies import get_campaign_calls_reader, get_health_reader
from app.config import Settings
from app.enums import ConsumerState
from app.exceptions import StorageUnavailableError
from app.main import create_app
from app.models import Call, Campaign
from app.services.readers import CampaignCallsReader, HealthReader
from tests.fakes import InMemoryStores

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def stores() -> InMemoryStores:
    stores = InMemoryStores()
    stores.campaigns.items["camp_001"] = Campaign("camp_001", "Напоминание о платеже", T0)
    stores.campaigns.items["camp_002"] = Campaign("camp_002", "Опрос", T0)
    stores.campaigns.items["camp_empty"] = Campaign("camp_empty", "Пустая", T0)
    for i, camp in enumerate(["camp_001", "camp_001", "camp_002", "camp_001"]):
        call = Call(f"call_{i}", camp, "79001234567", "success", T0 + timedelta(minutes=10 - i))
        stores.calls.items[call.call_id] = call
    return stores


class HealthState:
    def __init__(self) -> None:
        self.mongo_ok = True
        self.consumer = ConsumerState.CONSUMING

    async def ping(self) -> bool:
        return self.mongo_ok

    def consumer_state(self) -> ConsumerState:
        return self.consumer


@pytest.fixture
def health_state() -> HealthState:
    return HealthState()


@pytest.fixture
def app(stores: InMemoryStores, health_state: HealthState) -> FastAPI:
    app = create_app(Settings(), run_consumer=False)
    reader = CampaignCallsReader(stores.campaigns, stores.calls)
    health = HealthReader(health_state.ping, health_state.consumer_state)
    app.dependency_overrides[get_campaign_calls_reader] = lambda: reader
    app.dependency_overrides[get_health_reader] = lambda: health
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_returns_only_calls_of_campaign_sorted(client: httpx.AsyncClient) -> None:
    resp = await client.get("/campaigns/camp_001/calls")
    assert resp.status_code == 200
    body = resp.json()
    assert body["campaign_id"] == "camp_001"
    assert body["total"] == 3
    assert [c["call_id"] for c in body["calls"]] == ["call_3", "call_1", "call_0"]
    assert {c["campaign_id"] for c in body["calls"]} == {"camp_001"}
    assert body["calls"][0] == {
        "call_id": "call_3",
        "campaign_id": "camp_001",
        "phone": "79001234567",
        "status": "success",
        "created_at": "2026-10-20T10:07:00Z",
    }


async def test_pagination(client: httpx.AsyncClient) -> None:
    body = (await client.get("/campaigns/camp_001/calls?limit=1&offset=1")).json()
    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (1, 1)
    assert [c["call_id"] for c in body["calls"]] == ["call_1"]


async def test_existing_campaign_without_calls(client: httpx.AsyncClient) -> None:
    body = (await client.get("/campaigns/camp_empty/calls")).json()
    assert body["total"] == 0
    assert body["calls"] == []


async def test_missing_campaign_returns_200_with_text(client: httpx.AsyncClient) -> None:
    resp = await client.get("/campaigns/camp_404/calls")
    assert resp.status_code == 200
    assert resp.json() == {"detail": "Кампания не найдена"}
    assert "Кампания не найдена" in resp.text  # not \\u-escaped


async def test_storage_outage_returns_503(
    client: httpx.AsyncClient, stores: InMemoryStores
) -> None:
    stores.campaigns.fail_with = StorageUnavailableError("down")
    resp = await client.get("/campaigns/camp_001/calls")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Хранилище временно недоступно"}


@pytest.mark.parametrize(
    "url",
    [
        "/campaigns/bad%20id/calls",
        "/campaigns/camp_001/calls?limit=0",
        "/campaigns/camp_001/calls?limit=1001",
        "/campaigns/camp_001/calls?offset=-1",
    ],
)
async def test_invalid_params_422(client: httpx.AsyncClient, url: str) -> None:
    assert (await client.get(url)).status_code == 422


async def test_health_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_health_503_when_consumer_not_attached(
    client: httpx.AsyncClient, health_state: HealthState
) -> None:
    health_state.consumer = ConsumerState.BACKOFF
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "unavailable",
        "mongodb": {"ok": True, "state": "up"},
        "consumer": {"ok": False, "state": "backoff"},
    }


async def test_openapi_describes_all_response_shapes(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    assert {
        "CampaignCallsResponse",
        "CampaignNotFoundResponse",
        "CallOut",
        "ErrorResponse",
        "HealthResponse",
    } <= set(schemas)
    op = spec["paths"]["/campaigns/{campaign_id}/calls"]["get"]
    refs = str(op["responses"]["200"]["content"]["application/json"]["schema"])
    assert "CampaignCallsResponse" in refs
    assert "CampaignNotFoundResponse" in refs
    assert "ErrorResponse" in str(op["responses"]["503"])
    params = {p["name"]: p["in"] for p in op["parameters"]}
    assert params == {"campaign_id": "path", "limit": "query", "offset": "query"}
    assert (await client.get("/docs")).status_code == 200
