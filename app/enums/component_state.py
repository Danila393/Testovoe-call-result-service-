from __future__ import annotations

import enum


class ComponentState(str, enum.Enum):
    """State of a dependency that is either reachable or not (MongoDB)."""

    UP = "up"
    DOWN = "down"
