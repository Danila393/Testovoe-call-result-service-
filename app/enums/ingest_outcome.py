from __future__ import annotations

import enum


class IngestOutcome(str, enum.Enum):
    """What happened to a message; decides how the consumer settles it."""

    STORED = "stored"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    CONFLICT = "conflict"

    @property
    def should_ack(self) -> bool:
        """Ack only what is safely in the database; the rest is dead-lettered."""
        return self in (IngestOutcome.STORED, IngestOutcome.DUPLICATE)
