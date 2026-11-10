from __future__ import annotations

import producer
from app.dto import CallMessage
from app.infrastructure import rabbitmq


def test_producer_topology_matches_app() -> None:
    assert producer.EXCHANGE == rabbitmq.EXCHANGE
    assert producer.ROUTING_KEY == rabbitmq.ROUTING_KEY
    assert producer.QUEUE == rabbitmq.QUEUE
    assert producer.QUEUE_ARGUMENTS == rabbitmq.QUEUE_ARGUMENTS


def test_producer_messages_are_valid_and_cover_two_campaigns() -> None:
    parsed = [CallMessage.model_validate(m) for m in producer.MESSAGES]
    assert len(parsed) == 4
    per_campaign: dict[str, int] = {}
    for msg in parsed:
        per_campaign[msg.campaign_id] = per_campaign.get(msg.campaign_id, 0) + 1
    assert per_campaign == {"camp_001": 2, "camp_002": 2}
    assert len({m.call_id for m in parsed}) == 4
