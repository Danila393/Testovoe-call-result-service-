from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    name: str
    created_at: datetime
