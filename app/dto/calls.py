"""HTTP responses of ``GET /campaigns/{campaign_id}/calls``."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, Field

from app.dto.fields import IsoUtc
from app.models import Call, CallPage, PageParams

CAMPAIGN_NOT_FOUND: Final = "Кампания не найдена"


class CallOut(BaseModel):
    """A call as returned by the API."""

    call_id: str = Field(examples=["call_0001"])
    campaign_id: str = Field(examples=["camp_001"])
    phone: str = Field(examples=["79001234567"])
    status: str = Field(examples=["success"])
    created_at: IsoUtc = Field(examples=["2026-10-20T10:06:00Z"])

    @classmethod
    def from_call(cls, call: Call) -> CallOut:
        return cls(
            call_id=call.call_id,
            campaign_id=call.campaign_id,
            phone=call.phone,
            status=call.status,
            created_at=call.created_at,
        )


class CampaignCallsResponse(BaseModel):
    """Calls of an existing campaign, ordered by ``created_at`` then ``call_id``."""

    campaign_id: str = Field(examples=["camp_001"])
    total: int = Field(ge=0, description="Total number of calls in the campaign")
    limit: int
    offset: int
    calls: list[CallOut]

    @classmethod
    def from_page(
        cls, campaign_id: str, page: CallPage, params: PageParams
    ) -> CampaignCallsResponse:
        return cls(
            campaign_id=campaign_id,
            total=page.total,
            limit=params.limit,
            offset=params.offset,
            calls=[CallOut.from_call(call) for call in page.calls],
        )


class CampaignNotFoundResponse(BaseModel):
    """Returned with HTTP 200 when the campaign does not exist."""

    detail: Literal["Кампания не найдена"] = CAMPAIGN_NOT_FOUND
