from __future__ import annotations

import producer
from app import messaging
from app.schemas import CallMessage


def test_producer_topology_matches_app():
    assert producer.EXCHANGE == messaging.EXCHANGE
    assert producer.ROUTING_KEY == messaging.ROUTING_KEY
    assert producer.QUEUE == messaging.QUEUE
    assert producer.QUEUE_ARGUMENTS == messaging.QUEUE_ARGUMENTS


def test_producer_messages_are_valid_and_cover_two_campaigns():
    parsed = [CallMessage.model_validate(m) for m in producer.MESSAGES]
    assert len(parsed) == 4
    per_campaign: dict[str, int] = {}
    for msg in parsed:
        per_campaign[msg.campaign_id] = per_campaign.get(msg.campaign_id, 0) + 1
    assert per_campaign == {"camp_001": 2, "camp_002": 2}
    assert len({m.call_id for m in parsed}) == 4
