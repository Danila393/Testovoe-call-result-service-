"""Storage ports used by the service layer. Implementations raise ``StorageUnavailableError``
for transient failures."""

from __future__ import annotations

from typing import Protocol

from app.models import Call, CallPage, Campaign, InsertCallResult


class CampaignStore(Protocol):
    async def ensure(self, campaign: Campaign) -> Campaign:
        """Create the campaign if absent. Returns the stored campaign (first write wins)."""

    async def get(self, campaign_id: str) -> Campaign | None: ...


class CallStore(Protocol):
    async def insert(self, call: Call) -> InsertCallResult: ...

    async def page_by_campaign(self, campaign_id: str, *, limit: int, offset: int) -> CallPage:
        """One page of a campaign's calls and their total, read in a single query."""
