"""HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from pymongo import AsyncMongoClient

from app.consumer import CallConsumer, ConsumerState
from app.db import ping
from app.repository import CallStore, CampaignStore, Document
from app.schemas import (
    ID_PATTERN,
    CallOut,
    CampaignCallsResponse,
    CampaignNotFoundResponse,
    ComponentHealth,
    HealthResponse,
)

router = APIRouter()

MAX_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class Stores:
    campaigns: CampaignStore
    calls: CallStore


def get_stores(request: Request) -> Stores:
    stores: Stores = request.app.state.stores
    return stores


@router.get(
    "/campaigns/{campaign_id}/calls",
    response_model=CampaignCallsResponse | CampaignNotFoundResponse,
    summary="Звонки кампании",
    description=(
        "Возвращает звонки указанной кампании, отсортированные по `created_at`, затем `call_id`. "
        'Если кампании нет - `200` и `{"detail": "Кампания не найдена"}`.'
    ),
    tags=["campaigns"],
)
async def list_campaign_calls(
    stores: Annotated[Stores, Depends(get_stores)],
    campaign_id: Annotated[str, Path(pattern=ID_PATTERN, examples=["camp_001"])],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CampaignCallsResponse | CampaignNotFoundResponse:
    campaign = await stores.campaigns.get(campaign_id)
    if campaign is None:
        return CampaignNotFoundResponse()
    page = await stores.calls.page_by_campaign(campaign_id, limit=limit, offset=offset)
    return CampaignCallsResponse(
        campaign_id=campaign_id,
        total=page.total,
        limit=limit,
        offset=offset,
        calls=[CallOut.from_call(c) for c in page.calls],
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is not ready"}},
    summary="Готовность сервиса",
    tags=["service"],
)
async def health(request: Request, response: Response) -> HealthResponse:
    client: AsyncMongoClient[Document] = request.app.state.mongo_client
    consumer: CallConsumer | None = request.app.state.consumer
    mongo_ok = await ping(client)
    consumer_state = consumer.state if consumer is not None else ConsumerState.STOPPED
    consumer_ok = consumer_state is ConsumerState.CONSUMING
    ok = mongo_ok and consumer_ok
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if ok else "unavailable",
        mongodb=ComponentHealth(ok=mongo_ok, state="up" if mongo_ok else "down"),
        consumer=ComponentHealth(ok=consumer_ok, state=consumer_state.value),
    )
