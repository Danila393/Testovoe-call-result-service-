from __future__ import annotations

import enum


class ConsumerState(str, enum.Enum):
    """Lifecycle of the RabbitMQ consumer (docs/ARCHITECTURE.md, section 7)."""

    CREATED = "created"
    CONNECTING = "connecting"
    CONSUMING = "consuming"
    BACKOFF = "backoff"
    STOPPED = "stopped"
