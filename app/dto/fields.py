"""Reusable field types and validation patterns."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Final

from pydantic import AfterValidator, AwareDatetime, PlainSerializer, StringConstraints

ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"
PHONE_PATTERN: Final = r"^[1-9][0-9]{9,14}$"
STATUS_PATTERN: Final = r"^[a-z][a-z0-9_]{0,31}$"


def to_utc_millis(value: datetime) -> datetime:
    """Normalise to UTC and truncate to milliseconds, the precision of a BSON date.

    Without truncation a re-delivered message would not compare equal to the stored call.
    """
    value = value.astimezone(timezone.utc)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def to_iso_z(value: datetime) -> str:
    text = value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    text = text.removesuffix("+00:00") + "Z"
    return text.replace(".000Z", "Z")


EntityId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
Phone = Annotated[str, StringConstraints(pattern=PHONE_PATTERN)]
CallStatus = Annotated[str, StringConstraints(pattern=STATUS_PATTERN)]
CampaignName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(to_utc_millis)]
IsoUtc = Annotated[datetime, PlainSerializer(to_iso_z, return_type=str, when_used="json")]
