"""Domain entities stored in MongoDB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Call:
    call_id: str
    campaign_id: str
    phone: str
    status: str
    created_at: datetime
