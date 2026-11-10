"""FastAPI dependencies. Routes receive everything through ``Depends``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Query, Request

from app.container import Container
from app.dto.fields import ID_PATTERN
from app.models import PageParams
from app.models.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.services.readers import CampaignCallsReader, HealthReader


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_campaign_calls_reader(container: ContainerDep) -> CampaignCallsReader:
    return container.campaign_calls_reader


def get_health_reader(container: ContainerDep) -> HealthReader:
    return container.health_reader


def get_campaign_id(
    campaign_id: Annotated[str, Path(pattern=ID_PATTERN, examples=["camp_001"])],
) -> str:
    return campaign_id


def get_page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


CampaignCallsReaderDep = Annotated[CampaignCallsReader, Depends(get_campaign_calls_reader)]
HealthReaderDep = Annotated[HealthReader, Depends(get_health_reader)]
CampaignIdDep = Annotated[str, Depends(get_campaign_id)]
PageParamsDep = Annotated[PageParams, Depends(get_page_params)]
