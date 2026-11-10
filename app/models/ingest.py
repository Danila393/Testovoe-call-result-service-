"""Command and result of ingesting one queue message."""

from __future__ import annotations

from dataclasses import dataclass

from app.enums import IngestOutcome


@dataclass(frozen=True, slots=True)
class IngestCallCommand:
    """Raw message body as received from the broker; validation is the handler's job."""

    body: bytes


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: IngestOutcome
    call_id: str | None = None
    reason: str | None = None
