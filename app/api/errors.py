"""Maps application exceptions to HTTP responses, in one place."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.dto import CampaignNotFoundResponse, ErrorResponse
from app.exceptions import CampaignNotFoundError, ServiceNotReadyError, StorageUnavailableError

logger = logging.getLogger(__name__)

STORAGE_UNAVAILABLE = "Хранилище временно недоступно"


# Starlette types handlers as (Request, Exception); each one is registered for a single type.


async def campaign_not_found(_: Request, exc: Exception) -> JSONResponse:
    # The task requires HTTP 200 for a missing campaign, with a described body.
    logger.info("campaign not found", extra={"error": str(exc)})
    return JSONResponse(CampaignNotFoundResponse().model_dump(mode="json"), status.HTTP_200_OK)


async def service_not_ready(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ServiceNotReadyError):
        raise exc
    return JSONResponse(exc.report.model_dump(mode="json"), status.HTTP_503_SERVICE_UNAVAILABLE)


async def storage_unavailable(_: Request, exc: Exception) -> JSONResponse:
    logger.warning("storage unavailable while serving a request", extra={"error": str(exc)})
    body = ErrorResponse(detail=STORAGE_UNAVAILABLE).model_dump(mode="json")
    return JSONResponse(body, status.HTTP_503_SERVICE_UNAVAILABLE)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(CampaignNotFoundError, campaign_not_found)
    app.add_exception_handler(ServiceNotReadyError, service_not_ready)
    app.add_exception_handler(StorageUnavailableError, storage_unavailable)
