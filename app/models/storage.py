"""Results returned by repositories."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.call import Call


@dataclass(frozen=True, slots=True)
class InsertCallResult:
    """Result of inserting a call.

    ``inserted`` is True when the call was written now; otherwise ``existing`` is the stored one.
    """

    inserted: bool
    existing: Call | None = None


@dataclass(frozen=True, slots=True)
class CallPage:
    """One page of a campaign's calls and the campaign's total number of calls."""

    calls: list[Call]
    total: int
