"""Reader: calls of one campaign."""

from __future__ import annotations

from app.dto import CampaignCallsResponse
from app.exceptions import CampaignNotFoundError
from app.models import PageParams
from app.repositories import CallStore, CampaignStore


class CampaignCallsReader:
    def __init__(self, campaigns: CampaignStore, calls: CallStore) -> None:
        self._campaigns = campaigns
        self._calls = calls

    async def read(self, campaign_id: str, page: PageParams) -> CampaignCallsResponse:
        """Raises ``CampaignNotFoundError`` if the campaign does not exist."""
        if await self._campaigns.get(campaign_id) is None:
            raise CampaignNotFoundError(campaign_id)
        calls = await self._calls.page_by_campaign(
            campaign_id, limit=page.limit, offset=page.offset
        )
        return CampaignCallsResponse.from_page(campaign_id, calls, page)
