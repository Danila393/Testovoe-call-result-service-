"""Inbound message of the ``calls.results`` queue (docs/ARCHITECTURE.md, section 4)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.dto.fields import CallStatus, CampaignName, EntityId, Phone, UtcDatetime
from app.models import Call, Campaign


class CallMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    call_id: EntityId
    campaign_id: EntityId
    # Not part of the call format in the task: optional, defaults to campaign_id.
    campaign_name: CampaignName | None = None
    campaign_created_at: UtcDatetime | None = None
    phone: Phone
    status: CallStatus
    created_at: UtcDatetime

    def to_campaign(self) -> Campaign:
        return Campaign(
            campaign_id=self.campaign_id,
            name=self.campaign_name or self.campaign_id,
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
