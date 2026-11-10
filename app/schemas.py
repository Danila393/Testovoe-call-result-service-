"""Pydantic schemas: the inbound queue message and HTTP responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
)

from app.models import Call, Campaign

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"
PHONE_PATTERN = r"^[1-9][0-9]{9,14}$"
STATUS_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"

CAMPAIGN_NOT_FOUND: Final = "Кампания не найдена"


def to_utc_millis(value: datetime) -> datetime:
    """Normalise to UTC and truncate to milliseconds - the precision of a BSON date.

    Without truncation a re-delivered message would not compare equal to the stored call.
    """
    value = value.astimezone(timezone.utc)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def _iso_z(value: datetime) -> str:
    text = value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    text = text.removesuffix("+00:00") + "Z"
    return text.replace(".000Z", "Z")


EntityId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(to_utc_millis)]
IsoUtc = Annotated[datetime, PlainSerializer(_iso_z, return_type=str, when_used="json")]


class CallMessage(BaseModel):
    """Body of a message in the ``calls.results`` queue (see docs/ARCHITECTURE.md §4)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    call_id: EntityId
    campaign_id: EntityId
    campaign_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    campaign_created_at: UtcDatetime | None = None
    phone: Annotated[str, StringConstraints(pattern=PHONE_PATTERN)]
    status: Annotated[str, StringConstraints(pattern=STATUS_PATTERN)]
    created_at: UtcDatetime

    def to_campaign(self) -> Campaign:
        return Campaign(
            campaign_id=self.campaign_id,
            name=self.campaign_name,
            created_at=self.campaign_created_at or self.created_at,
        )

    def to_call(self) -> Call:
        return Call(
            call_id=self.call_id,
            campaign_id=self.campaign_id,
            phone=self.phone,
            status=self.status,
            created_at=self.created_at,
        )


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


class CampaignNotFoundResponse(BaseModel):
    """Returned with HTTP 200 when the campaign does not exist."""

    detail: Literal["Кампания не найдена"] = CAMPAIGN_NOT_FOUND


class ComponentHealth(BaseModel):
    ok: bool
    state: str


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    mongodb: ComponentHealth
    consumer: ComponentHealth
