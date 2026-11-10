from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Call:
    call_id: str
    campaign_id: str
    phone: str
    status: str
    created_at: datetime
