"""In-memory test doubles for the storage protocols in ``app.repositories.protocols``."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Call, CallPage, Campaign, InsertCallResult


class InMemoryCampaignStore:
    def __init__(self) -> None:
        self.items: dict[str, Campaign] = {}
        self.fail_with: Exception | None = None

    async def ensure(self, campaign: Campaign) -> Campaign:
        if self.fail_with is not None:
            raise self.fail_with
        return self.items.setdefault(campaign.campaign_id, campaign)

    async def get(self, campaign_id: str) -> Campaign | None:
        if self.fail_with is not None:
            raise self.fail_with
        return self.items.get(campaign_id)


class InMemoryCallStore:
    def __init__(self) -> None:
        self.items: dict[str, Call] = {}
        self.fail_with: Exception | None = None

    async def insert(self, call: Call) -> InsertCallResult:
        if self.fail_with is not None:
            raise self.fail_with
        if call.call_id in self.items:
            return InsertCallResult(inserted=False, existing=self.items[call.call_id])
        self.items[call.call_id] = call
        return InsertCallResult(inserted=True)

    async def page_by_campaign(self, campaign_id: str, *, limit: int, offset: int) -> CallPage:
        calls = sorted(
            (c for c in self.items.values() if c.campaign_id == campaign_id),
            key=lambda c: (c.created_at, c.call_id),
        )
        return CallPage(calls=calls[offset : offset + limit], total=len(calls))


@dataclass
class InMemoryStores:
    campaigns: InMemoryCampaignStore = field(default_factory=InMemoryCampaignStore)
    calls: InMemoryCallStore = field(default_factory=InMemoryCallStore)
