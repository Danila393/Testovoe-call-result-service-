from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import CampaignCallsReaderDep, CampaignIdDep, PageParamsDep
from app.dto import CampaignCallsResponse, CampaignNotFoundResponse, ErrorResponse

router = APIRouter(tags=["campaigns"])


@router.get(
    "/campaigns/{campaign_id}/calls",
    response_model=CampaignCallsResponse | CampaignNotFoundResponse,
    responses={503: {"model": ErrorResponse, "description": "MongoDB is unavailable"}},
    summary="Звонки кампании",
    description=(
        "Возвращает звонки указанной кампании, отсортированные по `created_at`, затем `call_id`. "
        'Если кампании нет: `200` и `{"detail": "Кампания не найдена"}`.'
    ),
)
async def list_campaign_calls(
    reader: CampaignCallsReaderDep,
    campaign_id: CampaignIdDep,
    page: PageParamsDep,
) -> CampaignCallsResponse:
    return await reader.read(campaign_id, page)
