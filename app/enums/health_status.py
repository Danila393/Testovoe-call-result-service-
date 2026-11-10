from __future__ import annotations

import enum


class HealthStatus(str, enum.Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
