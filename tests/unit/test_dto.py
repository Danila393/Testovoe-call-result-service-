from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.dto import CallMessage, CallOut, CampaignCallsResponse, CampaignNotFoundResponse
from app.models import Call, CallPage, PageParams
from tests.factories import message, task_format_message


def test_valid_message_maps_to_entities() -> None:
    msg = CallMessage.model_validate(message())
    assert msg.to_call() == Call(
        call_id="call_0001",
        campaign_id="camp_001",
        phone="79001234567",
        status="success",
        created_at=datetime(2026, 10, 20, 10, 6, tzinfo=timezone.utc),
    )
    campaign = msg.to_campaign()
    assert campaign.name == "Напоминание о платеже"
    assert campaign.created_at == datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


def test_task_format_message_is_valid_and_campaign_named_by_id() -> None:
    msg = CallMessage.model_validate(task_format_message())
    campaign = msg.to_campaign()
    assert campaign.campaign_id == "camp_003"
    assert campaign.name == "camp_003"
    assert campaign.created_at == msg.created_at


def test_campaign_created_at_defaults_to_call_time() -> None:
    msg = CallMessage.model_validate(message(campaign_created_at=...))
    assert msg.to_campaign().created_at == msg.created_at


def test_datetimes_normalised_to_utc_millis() -> None:
    msg = CallMessage.model_validate(message(created_at="2026-10-20T15:06:00.123456+05:00"))
    assert msg.created_at == datetime(2026, 10, 20, 10, 6, 0, 123000, tzinfo=timezone.utc)


def test_unknown_fields_ignored() -> None:
    msg = CallMessage.model_validate(message(duration_sec=42))
    assert not hasattr(msg, "duration_sec")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("call_id", ""),
        ("call_id", "has space"),
        ("call_id", "x" * 65),
        ("campaign_id", "-leading-dash"),
        ("campaign_name", "   "),
        ("campaign_name", "x" * 201),
        ("phone", "+79001234567"),
        ("phone", "123"),
        ("phone", "0900123456"),
        ("phone", 79001234567),
        ("status", "SUCCESS"),
        ("status", ""),
        ("created_at", "2026-10-20T10:06:00"),  # no timezone
        ("created_at", "yesterday"),
        ("campaign_created_at", "2026-10-20"),
        ("call_id", ...),
        ("created_at", ...),
        ("phone", "+7 900 123-45-67"),
    ],
)
def test_invalid_message_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CallMessage.model_validate(message(**{field: value}))


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        (datetime(2026, 10, 20, 10, 6, tzinfo=timezone.utc), "2026-10-20T10:06:00Z"),
        (datetime(2026, 10, 20, 10, 6, 0, 120000, tzinfo=timezone.utc), "2026-10-20T10:06:00.120Z"),
    ],
)
def test_call_out_serialises_iso_z(created_at: datetime, expected: str) -> None:
    call = Call("call_0001", "camp_001", "79001234567", "success", created_at)
    assert CallOut.from_call(call).model_dump(mode="json")["created_at"] == expected


def test_campaign_calls_response_from_page() -> None:
    call = Call("call_0001", "camp_001", "79001234567", "success", datetime.now(timezone.utc))
    response = CampaignCallsResponse.from_page(
        "camp_001", CallPage(calls=[call], total=7), PageParams(limit=1, offset=3)
    )
    assert (response.total, response.limit, response.offset) == (7, 1, 3)
    assert [c.call_id for c in response.calls] == ["call_0001"]


def test_not_found_text() -> None:
    assert CampaignNotFoundResponse().model_dump() == {"detail": "Кампания не найдена"}
