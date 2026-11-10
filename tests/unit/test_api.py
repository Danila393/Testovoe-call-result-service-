"""HTTP layer with in-memory stores (no lifespan, no external services)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api import Stores, get_stores
from app.config import Settings
from app.main import create_app
from app.models import Call, Campaign
from tests.fakes import InMemoryCallStore, InMemoryCampaignStore

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def stores() -> Stores:
    campaigns, calls = InMemoryCampaignStore(), InMemoryCallStore()
    campaigns.items["camp_001"] = Campaign("camp_001", "Напоминание о платеже", T0)
    campaigns.items["camp_002"] = Campaign("camp_002", "Опрос", T0)
    campaigns.items["camp_empty"] = Campaign("camp_empty", "Пустая", T0)
    for i, camp in enumerate(["camp_001", "camp_001", "camp_002", "camp_001"]):
        call = Call(f"call_{i}", camp, "79001234567", "success", T0 + timedelta(minutes=10 - i))
        calls.items[call.call_id] = call
    return Stores(campaigns=campaigns, calls=calls)


@pytest.fixture
async def client(stores) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(), run_consumer=False)
    app.dependency_overrides[get_stores] = lambda: stores
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_returns_only_calls_of_campaign_sorted(client):
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


async def test_pagination(client):
    body = (await client.get("/campaigns/camp_001/calls?limit=1&offset=1")).json()
    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (1, 1)
    assert [c["call_id"] for c in body["calls"]] == ["call_1"]


async def test_existing_campaign_without_calls(client):
    body = (await client.get("/campaigns/camp_empty/calls")).json()
    assert body["total"] == 0
    assert body["calls"] == []


async def test_missing_campaign_returns_200_with_text(client):
    resp = await client.get("/campaigns/camp_404/calls")
    assert resp.status_code == 200
    assert resp.json() == {"detail": "Кампания не найдена"}
    assert "Кампания не найдена" in resp.text  # not \\u-escaped


@pytest.mark.parametrize(
    "url",
    [
        "/campaigns/bad%20id/calls",
        "/campaigns/camp_001/calls?limit=0",
        "/campaigns/camp_001/calls?limit=1001",
        "/campaigns/camp_001/calls?offset=-1",
    ],
)
async def test_invalid_params_422(client, url):
    assert (await client.get(url)).status_code == 422


async def test_openapi_describes_both_response_shapes(client):
    spec = (await client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    assert {"CampaignCallsResponse", "CampaignNotFoundResponse", "CallOut"} <= set(schemas)
    op = spec["paths"]["/campaigns/{campaign_id}/calls"]["get"]
    refs = str(op["responses"]["200"]["content"]["application/json"]["schema"])
    assert "CampaignCallsResponse" in refs
    assert "CampaignNotFoundResponse" in refs
    assert (await client.get("/docs")).status_code == 200
