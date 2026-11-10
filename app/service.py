"""Business logic of ingesting one call-result message.

Transport-agnostic: takes raw bytes, returns an outcome. Storage failures are raised to the
caller, which decides on retry (see docs/ARCHITECTURE.md §6).
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.repository import CallStore, CampaignStore
from app.schemas import CallMessage

logger = logging.getLogger(__name__)

_MAX_LOGGED_BODY = 500


class Outcome(enum.Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    CONFLICT = "conflict"

    @property
    def should_ack(self) -> bool:
        return self in (Outcome.STORED, Outcome.DUPLICATE)


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: Outcome
    call_id: str | None = None
    reason: str | None = None


def _preview(body: bytes) -> str:
    text = body[:_MAX_LOGGED_BODY].decode("utf-8", errors="replace")
    return text + ("…" if len(body) > _MAX_LOGGED_BODY else "")


def parse_message(body: bytes) -> CallMessage | str:
    """Return the validated message or a human-readable reason why it is invalid."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"body is not valid UTF-8 JSON: {exc}"
    if not isinstance(payload, dict):
        return f"body must be a JSON object, got {type(payload).__name__}"
    try:
        return CallMessage.model_validate(payload)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors(include_url=False, include_input=False)
        )
        return f"validation failed: {errors}"


class CallIngestService:
    def __init__(self, campaigns: CampaignStore, calls: CallStore) -> None:
        self._campaigns = campaigns
        self._calls = calls

    async def ingest(self, body: bytes) -> IngestResult:
        parsed = parse_message(body)
        if isinstance(parsed, str):
            logger.warning(
                "invalid message rejected", extra={"reason": parsed, "body": _preview(body)}
            )
            return IngestResult(Outcome.INVALID, reason=parsed)

        campaign = parsed.to_campaign()
        stored_campaign = await self._campaigns.ensure(campaign)
        if stored_campaign.name != campaign.name:
            logger.warning(
                "campaign name differs from stored one; keeping stored",
                extra={
                    "campaign_id": campaign.campaign_id,
                    "stored_name": stored_campaign.name,
                    "message_name": campaign.name,
                    "call_id": parsed.call_id,
                },
            )

        call = parsed.to_call()
        result = await self._calls.insert(call)
        if result.inserted:
            logger.info(
                "call stored", extra={"call_id": call.call_id, "campaign_id": call.campaign_id}
            )
            return IngestResult(Outcome.STORED, call_id=call.call_id)

        if result.existing == call:
            logger.info("duplicate call skipped", extra={"call_id": call.call_id})
            return IngestResult(Outcome.DUPLICATE, call_id=call.call_id)

        reason = "call_id already stored with different data"
        logger.error(
            "conflicting duplicate rejected",
            extra={
                "call_id": call.call_id,
                "reason": reason,
                "stored": str(result.existing),
                "incoming": str(call),
            },
        )
        return IngestResult(Outcome.CONFLICT, call_id=call.call_id, reason=reason)
