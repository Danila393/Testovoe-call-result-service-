"""Application exceptions. The service layer raises them; ``app.api.errors`` maps them to HTTP."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.dto.health import HealthResponse


class AppError(Exception):
    """Base class for errors the service layer reports on purpose."""


class CampaignNotFoundError(AppError):
    def __init__(self, campaign_id: str) -> None:
        super().__init__(f"campaign {campaign_id!r} not found")
        self.campaign_id = campaign_id


class StorageUnavailableError(AppError):
    """The database is temporarily unreachable; the same operation may succeed later."""


class ServiceNotReadyError(AppError):
    """A dependency the service needs is not ready; ``report`` says which."""

    def __init__(self, report: HealthResponse) -> None:
        super().__init__("service is not ready")
        self.report = report
